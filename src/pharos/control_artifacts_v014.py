"""Deterministic, bounded artifacts for Pharos v0.1.4.

The public helpers in this module never follow artifact-provided symlinks and
never overwrite a published candidate.  Parquet imports are lazy so the
isolated parser worker can establish its address-space limit first.
"""

from __future__ import annotations

import ctypes
import hashlib
import math
import os
import re
import secrets
import stat
import struct
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final, Literal

import pandas as pd

from pharos.control_population_v014 import PREREGISTRATION_SHA256

MAX_PARQUET_BYTES: Final = 2_147_483_648
MAX_FOOTER_BYTES: Final = 16_777_216
MAX_METADATA_BYTES: Final = 1_048_576
MAX_COLUMNS: Final = 64
MAX_ROW_GROUPS: Final = 1_024
MAX_CHUNK_COMPRESSED: Final = 67_108_864
MAX_CHUNK_UNCOMPRESSED: Final = 134_217_728
MAX_FILE_COUNT: Final = 2_048
MAX_TREE_BYTES: Final = 4_294_967_296
MAX_RELATIVE_PATH_BYTES: Final = 240
MAX_COMPONENT_BYTES: Final = 180
PARSER_RLIMIT_AS: Final = 1_073_741_824
PARSER_ALLOCATOR_LIMIT: Final = 268_435_456
ROW_GROUP_SIZE: Final = 50_000
RENAME_EXCL: Final = 0x00000004
SEMANTIC_HASH_ALGORITHM: Final = "pharos-semantic-frame-le-v1"
PARQUET_WRITER_PROFILE: Final = "pharos-parquet-v014"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _renameatx_np(parent_fd: int, source_name: str, destination_name: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameatx = getattr(libc, "renameatx_np", None)
    if renameatx is None:
        raise RuntimeError("required macOS renameatx_np primitive is unavailable")
    renameatx.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameatx.restype = ctypes.c_int
    result = renameatx(
        parent_fd,
        source_name.encode(),
        parent_fd,
        destination_name.encode(),
        RENAME_EXCL,
    )
    if result != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), destination_name)


def probe_rename_excl(parent: Path) -> None:
    """Demonstrate the required same-filesystem no-replace primitive."""
    parent = parent.resolve(strict=True)
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    source = f".pharos-rename-probe-source-{secrets.token_hex(8)}"
    destination = f".pharos-rename-probe-destination-{secrets.token_hex(8)}"
    try:
        os.mkdir(source, mode=0o700, dir_fd=parent_fd)
        _renameatx_np(parent_fd, source, destination)
        opened = os.open(
            destination,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        os.close(opened)
        os.rmdir(destination, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        for name in (source, destination):
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


@dataclass(frozen=True)
class Column:
    name: str
    logical_type: Literal["int64", "float64", "bool", "string", "timestamp[us,UTC]"]
    nullable: bool


@dataclass(frozen=True)
class ArtifactIdentity:
    path: str
    byte_sha256: str
    semantic_sha256: str | None
    bytes: int
    rows: int | None
    schema_version: str
    columns: tuple[str, ...] | None


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("artifact is not a regular file")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def validate_relative_path(value: str) -> PurePosixPath:
    """Validate one artifact path without consulting the filesystem."""
    if type(value) is not str or not value or "\x00" in value or "\\" in value:
        raise ValueError("artifact path must be a non-empty NUL-free POSIX path")
    encoded = value.encode("utf-8")
    if len(encoded) > MAX_RELATIVE_PATH_BYTES:
        raise ValueError("artifact path exceeds registered byte bound")
    raw_parts = value.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise ValueError("artifact path contains an empty, dot, or traversal component")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or value in (".", "..")
        or any(part in ("", ".", "..") for part in posix.parts)
        or windows.is_absolute()
        or windows.drive
    ):
        raise ValueError("artifact path is absolute, ambiguous, drive-based, or traversing")
    if any(len(part.encode("utf-8")) > MAX_COMPONENT_BYTES for part in posix.parts):
        raise ValueError("artifact path component exceeds registered byte bound")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError("artifact path is not NFC-normalized")
    return posix


def _u64(value: int) -> bytes:
    if type(value) is not int or not 0 <= value <= 2**64 - 1:
        raise ValueError("semantic-frame length is outside uint64")
    return struct.pack("<Q", value)


def _field_text(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return _u64(len(encoded)) + encoded


def _encode_cell(value: object, column: Column) -> bytes:
    if value is None or pd.isna(value):
        if not column.nullable:
            raise ValueError(f"{column.name} is null but non-nullable")
        return b"\x00"
    prefix = b"\x01"
    if column.logical_type == "int64":
        if isinstance(value, bool) or not isinstance(value, int):
            # pandas/numpy scalar support without coercing arbitrary strings.
            try:
                import numpy as np

                if not isinstance(value, np.integer):
                    raise TypeError
            except (ImportError, TypeError) as exc:
                raise TypeError(f"{column.name} is not int64") from exc
        integer = int(value)
        if not -(2**63) <= integer <= 2**63 - 1:
            raise ValueError(f"{column.name} outside int64")
        return prefix + struct.pack("<q", integer)
    if column.logical_type == "float64":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            try:
                import numpy as np

                if not isinstance(value, (np.integer, np.floating)):
                    raise TypeError
            except (ImportError, TypeError) as exc:
                raise TypeError(f"{column.name} is not float64") from exc
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{column.name} is non-finite")
        if number == 0.0:
            number = 0.0
        return prefix + struct.pack("<d", number)
    if column.logical_type == "bool":
        if not isinstance(value, bool):
            try:
                import numpy as np

                if not isinstance(value, np.bool_):
                    raise TypeError
            except (ImportError, TypeError) as exc:
                raise TypeError(f"{column.name} is not bool") from exc
        return prefix + (b"\x01" if bool(value) else b"\x00")
    if column.logical_type == "string":
        if not isinstance(value, str):
            raise TypeError(f"{column.name} is not string")
        normalized = unicodedata.normalize("NFC", value)
        if value != normalized or "\x00" in value:
            raise ValueError(f"{column.name} is not canonical UTF-8 text")
        encoded = value.encode("utf-8")
        return prefix + _u64(len(encoded)) + encoded
    if column.logical_type == "timestamp[us,UTC]":
        timestamp = pd.Timestamp(value)
        if timestamp.tz is None or str(timestamp.tz) not in ("UTC", "UTC+00:00"):
            raise ValueError(f"{column.name} timestamp is not UTC")
        micros = int(timestamp.value // 1_000)
        return prefix + struct.pack("<q", micros)
    raise AssertionError("unregistered semantic logical type")


def semantic_sha256(frame: pd.DataFrame, schema_version: str, columns: Sequence[Column]) -> str:
    """Hash a table using the registered semantic frame (never pandas hashes)."""
    if tuple(frame.columns) != tuple(column.name for column in columns):
        raise ValueError("semantic table columns do not match registered order")
    digest = hashlib.sha256()
    schema = schema_version.encode("ascii")
    digest.update(_u64(len(schema)))
    digest.update(schema)
    digest.update(_u64(len(frame)))
    for column in columns:
        digest.update(_field_text(column.name))
        digest.update(_field_text(column.logical_type))
    for row in frame.itertuples(index=False, name=None):
        for value, column in zip(row, columns, strict=True):
            digest.update(_encode_cell(value, column))
    return digest.hexdigest()


def parquet_metadata(
    *, schema_version: str, source_tree_sha256: str, uv_lock_sha256: str
) -> dict[bytes, bytes]:
    for name, digest in (
        ("pre-registration", PREREGISTRATION_SHA256),
        ("source-tree", source_tree_sha256),
        ("uv-lock", uv_lock_sha256),
    ):
        if _HEX64.fullmatch(digest) is None:
            raise ValueError(f"{name} digest is not lowercase SHA-256")
    values = {
        "pharos.pre_registration_sha256": PREREGISTRATION_SHA256,
        "pharos.schema_version": schema_version,
        "pharos.source_tree_sha256": source_tree_sha256,
        "pharos.uv_lock_sha256": uv_lock_sha256,
        "pharos.writer_profile": PARQUET_WRITER_PROFILE,
    }
    return {key.encode(): values[key].encode() for key in sorted(values)}


def write_deterministic_parquet(
    frame: pd.DataFrame,
    path: Path,
    *,
    schema_version: str,
    columns: Sequence[Column],
    source_tree_sha256: str,
    uv_lock_sha256: str,
) -> ArtifactIdentity:
    """Create one exact-profile content payload at a new path."""
    if path.exists() or path.is_symlink():
        raise FileExistsError("refusing to replace a Parquet artifact")
    if tuple(frame.columns) != tuple(column.name for column in columns):
        raise ValueError("Parquet frame columns do not match registered schema")
    import pyarrow as pa
    import pyarrow.parquet as pq

    type_map = {
        "int64": pa.int64(),
        "float64": pa.float64(),
        "bool": pa.bool_(),
        "string": pa.string(),
        "timestamp[us,UTC]": pa.timestamp("us", tz="UTC"),
    }
    arrow_schema = pa.schema(
        [
            pa.field(column.name, type_map[column.logical_type], nullable=column.nullable)
            for column in columns
        ],
        metadata=parquet_metadata(
            schema_version=schema_version,
            source_tree_sha256=source_tree_sha256,
            uv_lock_sha256=uv_lock_sha256,
        ),
    )
    table = pa.Table.from_pandas(frame, schema=arrow_schema, preserve_index=False, safe=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as output:
            pq.write_table(
                table,
                output,
                version="2.6",
                compression="zstd",
                compression_level=9,
                use_dictionary=False,
                write_statistics=True,
                row_group_size=ROW_GROUP_SIZE,
                data_page_version="2.0",
                write_page_index=False,
                store_schema=False,
            )
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(fd)
    size = path.stat(follow_symlinks=False).st_size
    if size > MAX_PARQUET_BYTES:
        raise ValueError("Parquet artifact exceeds registered byte bound")
    identity = ArtifactIdentity(
        path=path.name,
        byte_sha256=sha256_file(path),
        semantic_sha256=semantic_sha256(frame, schema_version, columns),
        bytes=size,
        rows=len(frame),
        schema_version=schema_version,
        columns=tuple(column.name for column in columns),
    )
    return identity


def preflight_parquet(path: Path, *, expected: ArtifactIdentity) -> None:
    """Reject malformed/oversized Parquet declarations before materialization."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ValueError("Parquet input is not a private regular file")
        if opened.st_size != expected.bytes or opened.st_size > MAX_PARQUET_BYTES:
            raise ValueError("Parquet size does not match bounded descriptor")
        if opened.st_size < 12:
            raise ValueError("Parquet file is too small")
        if os.pread(fd, 4, 0) != b"PAR1" or os.pread(fd, 4, opened.st_size - 4) != b"PAR1":
            raise ValueError("Parquet terminal magic is invalid")
        footer_bytes = struct.unpack("<I", os.pread(fd, 4, opened.st_size - 8))[0]
        if footer_bytes > MAX_FOOTER_BYTES or footer_bytes + 12 > opened.st_size:
            raise ValueError("Parquet footer declaration is invalid or oversized")
        if sha256_file(path) != expected.byte_sha256:
            raise ValueError("Parquet byte SHA-256 mismatch")
    finally:
        os.close(fd)
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    metadata = parquet.metadata
    if metadata.num_columns > MAX_COLUMNS or metadata.num_row_groups > MAX_ROW_GROUPS:
        raise ValueError("Parquet structural count exceeds registered bound")
    if metadata.num_rows != expected.rows or tuple(parquet.schema_arrow.names) != expected.columns:
        raise ValueError("Parquet row/column descriptor mismatch")
    if any(field.type.num_fields > 0 for field in parquet.schema_arrow):
        raise ValueError("nested Parquet fields are forbidden")
    encoded_metadata = sum(
        len(str(key).encode()) + len(str(value).encode())
        for key, value in (parquet.schema_arrow.metadata or {}).items()
    )
    if encoded_metadata > MAX_METADATA_BYTES:
        raise ValueError("Parquet key/value metadata exceeds registered bound")
    size = path.stat().st_size
    for group_index in range(metadata.num_row_groups):
        group = metadata.row_group(group_index)
        if group.num_rows < 0 or group.num_rows > ROW_GROUP_SIZE:
            raise ValueError("Parquet row-group row count is invalid")
        for column_index in range(group.num_columns):
            chunk = group.column(column_index)
            if (
                chunk.total_compressed_size > MAX_CHUNK_COMPRESSED
                or chunk.total_uncompressed_size > MAX_CHUNK_UNCOMPRESSED
            ):
                raise ValueError("Parquet column chunk exceeds registered bound")
            offset = min(
                value
                for value in (chunk.data_page_offset, chunk.dictionary_page_offset)
                if value is not None and value >= 0
            )
            if offset < 4 or offset + chunk.total_compressed_size > size - 8:
                raise ValueError("Parquet column chunk escapes file")


def establish_parser_address_space_limit() -> None:
    """Forward to the authoritative pre-import network/parser boundary."""
    from pharos.control_network_v014 import establish_parser_address_space_limit as establish

    establish()


def _mkdir_chain(root_fd: int, path: PurePosixPath) -> None:
    current_fd = os.dup(root_fd)
    try:
        for part in path.parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current_fd,
            )
            opened = os.fstat(child)
            if not stat.S_ISDIR(opened.st_mode) or opened.st_nlink < 2:
                os.close(child)
                raise ValueError("staging path component is not a directory")
            os.close(current_fd)
            current_fd = child
    finally:
        os.close(current_fd)


class CandidateTreeWriter:
    """Descriptor-relative private candidate staging with manifest-last publish."""

    def __init__(
        self, parent: Path, final_name: str, *, manifest_name: str = "manifest.yaml"
    ) -> None:
        if "/" in final_name or final_name in ("", ".", ".."):
            raise ValueError("final candidate name must be one path component")
        self.parent = parent.resolve(strict=True)
        self.final_name = final_name
        if manifest_name not in ("manifest.yaml", "checkpoint_manifest.yaml"):
            raise ValueError("candidate manifest filename is not registered")
        self.manifest_name = manifest_name
        self.parent_fd = os.open(self.parent, os.O_RDONLY | os.O_DIRECTORY)
        self.staging_name = f".{final_name}.staging-{secrets.token_hex(12)}"
        os.mkdir(self.staging_name, mode=0o700, dir_fd=self.parent_fd)
        self.staging_fd = os.open(
            self.staging_name,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=self.parent_fd,
        )
        self._files: dict[str, tuple[int, int, str, int]] = {}
        self._published = False
        self._closed = False

    @property
    def staging_path(self) -> Path:
        return self.parent / self.staging_name

    @property
    def payload_identities(self) -> tuple[ArtifactIdentity, ...]:
        identities: list[ArtifactIdentity] = []
        for relative, (_, _, digest, size) in self._files.items():
            identities.append(ArtifactIdentity(relative, digest, None, size, None, "binary", None))
        return tuple(identities)

    def write_parquet(
        self,
        relative: str,
        frame: pd.DataFrame,
        *,
        schema_version: str,
        columns: Sequence[Column],
        source_tree_sha256: str,
        uv_lock_sha256: str,
    ) -> ArtifactIdentity:
        path = validate_relative_path(relative)
        if relative in self._files or relative == self.manifest_name:
            raise ValueError("duplicate payload or premature manifest")
        if len(path.parts) > 1:
            _mkdir_chain(self.staging_fd, PurePosixPath(*path.parts[:-1]))
        target = self.staging_path / relative
        identity = write_deterministic_parquet(
            frame,
            target,
            schema_version=schema_version,
            columns=columns,
            source_tree_sha256=source_tree_sha256,
            uv_lock_sha256=uv_lock_sha256,
        )
        opened = target.stat(follow_symlinks=False)
        relative_identity = ArtifactIdentity(
            relative,
            identity.byte_sha256,
            identity.semantic_sha256,
            identity.bytes,
            identity.rows,
            identity.schema_version,
            identity.columns,
        )
        self._files[relative] = (
            opened.st_dev,
            opened.st_ino,
            relative_identity.byte_sha256,
            relative_identity.bytes,
        )
        return relative_identity

    def write_content_addressed_parquet(
        self,
        directory: str,
        prefix: str,
        frame: pd.DataFrame,
        *,
        schema_version: str,
        columns: Sequence[Column],
        source_tree_sha256: str,
        uv_lock_sha256: str,
    ) -> ArtifactIdentity:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", prefix):
            raise ValueError("content-addressed Parquet prefix is invalid")
        if directory in ("", "."):
            base_prefix = ""
        else:
            base_prefix = validate_relative_path(directory).as_posix() + "/"
        temporary_name = f".{prefix}-{secrets.token_hex(8)}.parquet"
        temporary_relative = f"{base_prefix}{temporary_name}"
        temporary = self.write_parquet(
            temporary_relative,
            frame,
            schema_version=schema_version,
            columns=columns,
            source_tree_sha256=source_tree_sha256,
            uv_lock_sha256=uv_lock_sha256,
        )
        final_relative = f"{base_prefix}{prefix}.{temporary.byte_sha256}.parquet"
        validate_relative_path(final_relative)
        source = self.staging_path / temporary_relative
        target = self.staging_path / final_relative
        try:
            os.link(source, target, follow_symlinks=False)
        except FileExistsError as exc:
            raise FileExistsError("conflicting content-addressed Parquet payload") from exc
        source.unlink()
        old = self._files.pop(temporary_relative)
        opened = target.stat(follow_symlinks=False)
        if opened.st_nlink != 1:
            raise ValueError("content-addressed Parquet retains an unexpected hard link")
        identity = ArtifactIdentity(
            final_relative,
            temporary.byte_sha256,
            temporary.semantic_sha256,
            temporary.bytes,
            temporary.rows,
            temporary.schema_version,
            temporary.columns,
        )
        self._files[final_relative] = (opened.st_dev, opened.st_ino, old[2], old[3])
        return identity

    def write_bytes(self, relative: str, data: bytes) -> ArtifactIdentity:
        path = validate_relative_path(relative)
        if relative in self._files or relative == self.manifest_name:
            raise ValueError("duplicate payload or premature manifest")
        _mkdir_chain(self.staging_fd, PurePosixPath(*path.parts[:-1])) if len(
            path.parts
        ) > 1 else None
        directory_fd = os.dup(self.staging_fd)
        try:
            for part in path.parts[:-1]:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = child
            fd = os.open(
                path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            try:
                with os.fdopen(fd, "wb", closefd=False) as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                opened = os.fstat(fd)
                self._files[relative] = (
                    opened.st_dev,
                    opened.st_ino,
                    sha256_bytes(data),
                    len(data),
                )
            finally:
                os.close(fd)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return ArtifactIdentity(relative, sha256_bytes(data), None, len(data), None, "binary", None)

    def publish(self, manifest_bytes: bytes) -> Path:
        if self._closed:
            raise RuntimeError("candidate tree writer is closed")
        if self._published:
            raise RuntimeError("candidate tree already published")
        # Manifest is the filesystem commit marker and is always created last.
        fd = os.open(
            self.manifest_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=self.staging_fd,
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as handle:
                handle.write(manifest_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(fd)
        os.fsync(self.staging_fd)
        file_count = 0
        total = 0
        for root, directories, files in os.walk(self.staging_path, followlinks=False):
            for name in directories:
                candidate = Path(root, name)
                if candidate.is_symlink():
                    raise ValueError("staging directory contains symlink")
            for name in files:
                candidate = Path(root, name)
                opened = candidate.stat(follow_symlinks=False)
                if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                    raise ValueError("staging payload was link/inode substituted")
                file_count += 1
                total += opened.st_size
        if file_count > MAX_FILE_COUNT or total > MAX_TREE_BYTES:
            raise ValueError("candidate tree exceeds registered resource bound")
        for relative, (device, inode, digest, size) in self._files.items():
            candidate = self.staging_path / relative
            opened = candidate.stat(follow_symlinks=False)
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                device,
                inode,
                size,
            ) or sha256_file(candidate) != digest:
                raise ValueError("staging payload changed before publication")
        _renameatx_np(self.parent_fd, self.staging_name, self.final_name)
        os.fsync(self.parent_fd)
        self._published = True
        self.close_unpublished()
        return self.parent / self.final_name

    def close_unpublished(self) -> None:
        """Close owned descriptors without deleting or reusing staged evidence.

        A failed candidate is an operator-quarantine artifact under the frozen
        protocol.  Closing this writer therefore never removes its staging
        directory, even when publication did not complete.
        """
        if self._closed:
            return
        os.close(self.staging_fd)
        os.close(self.parent_fd)
        self._closed = True

    def close(self) -> None:
        """Idempotent descriptor-only close; staged bytes remain quarantined."""
        self.close_unpublished()
