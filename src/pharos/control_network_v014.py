"""Fail-closed network and parser boundary for the frozen v0.1.4 controls.

This module deliberately contains no acquisition workflow.  It provides the
small, dependency-free primitives that an acquisition worker must satisfy
before it can create scientific request evidence.  Remote data, environment
configuration, DNS answers, TLS peers, and transport records are all treated
as hostile inputs.
"""

from __future__ import annotations

import hashlib
import importlib
import ipaddress
import os
import re
import socket
import ssl
import stat
import sys
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType, ModuleType
from typing import Any, Final, Literal, NoReturn, cast
from urllib.parse import urlsplit
from uuid import UUID

PREREGISTRATION_SHA256: Final = "9c1751721a2021c632a8a86cfab6a67e1f23e1bcc84973a25dc156b2b5bc7999"
PREREGISTRATION_BYTES: Final = 4_936

PEER_PORT: Final = 443
TLS_VERSION: Final = "TLSv1.3"
# Frozen v0.1.6 Section 2.1: TLS 1.2 floor / 1.3 ceiling, AEAD-only.
TLS_VERSION_MIN: Final = "TLSv1.2"
TLS_VERSION_MAX: Final = "TLSv1.3"
TLS_VERSIONS: Final = ("TLSv1.3", "TLSv1.2")
TLS12_AEAD_CIPHERS: Final = (
    "ECDHE-ECDSA-AES256-GCM-SHA384"
    ":ECDHE-ECDSA-AES128-GCM-SHA256"
    ":ECDHE-RSA-AES256-GCM-SHA384"
    ":ECDHE-RSA-AES128-GCM-SHA256"
)
CA_BUNDLE_BYTES: Final = 234_072
CA_BUNDLE_SHA256: Final = "d87887200c9a705dccc937b9b83b5e67e47024c4a4b7f9dd15700c72e0f55453"
CA_BUNDLE_FILENAME: Final = f"ca_bundle.{CA_BUNDLE_SHA256}.pem"

WIRE_BYTES_MAX: Final = 33_554_432
DECOMPRESSED_RESPONSE_BYTES_MAX: Final = 67_108_864
PARSER_ALLOCATOR_BYTES_MAX: Final = 268_435_456
PARSER_ADDRESS_SPACE_BYTES_MAX: Final = 1_073_741_824
PROCESS_RSS_BYTES_MAX: Final = 1_073_741_824

TCP_CONNECT_TIMEOUT_SECONDS: Final = 10
TLS_HANDSHAKE_TIMEOUT_SECONDS: Final = 10
RESPONSE_HEADER_TIMEOUT_SECONDS: Final = 60
BODY_READ_TIMEOUT_SECONDS: Final = 600
GAIA_LOGICAL_DEADLINE_SECONDS: Final = 7_200
GAIA_POLL_INTERVAL_SECONDS: Final = 10
GAIA_POLL_OPERATIONS_MAX: Final = 720
SIMBAD_LOGICAL_DEADLINE_SECONDS: Final = 600
CHEN_LOGICAL_DEADLINE_SECONDS: Final = 600
TRANSPORT_ATTEMPTS_MAX: Final = 3
RETRY_WAITS_SECONDS: Final = (5, 15)
REDIRECTS_MAX: Final = 0

ServiceName = Literal["gaia", "simbad", "chen"]


@dataclass(frozen=True, slots=True)
class EndpointPolicy:
    service: ServiceName
    endpoint: str
    hostname: str
    path: str
    asynchronous: bool


_ENDPOINT_POLICIES: Final = (
    EndpointPolicy(
        "gaia",
        "https://gea.esac.esa.int/tap-server/tap",
        "gea.esac.esa.int",
        "/tap-server/tap",
        True,
    ),
    EndpointPolicy(
        "simbad",
        "https://simbad.cds.unistra.fr/simbad/sim-tap",
        "simbad.cds.unistra.fr",
        "/simbad/sim-tap",
        True,
    ),
    EndpointPolicy(
        "chen",
        "https://vizier.cds.unistra.fr/viz-bin/votable",
        "vizier.cds.unistra.fr",
        "/viz-bin/votable",
        False,
    ),
)
ENDPOINT_POLICIES: Final[Mapping[str, EndpointPolicy]] = MappingProxyType(
    {policy.service: policy for policy in _ENDPOINT_POLICIES}
)
ALLOWED_HOSTNAMES: Final = tuple(policy.hostname for policy in _ENDPOINT_POLICIES)

AMBIENT_NETWORK_ENVIRONMENT: Final = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "NETRC",
    "netrc",
    "CURL_HOME",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "AWS_CA_BUNDLE",
    "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH",
    "NODE_EXTRA_CA_CERTS",
    "PIP_CERT",
    "GIT_SSL_CAINFO",
)


class BoundaryErrorCode(str, Enum):
    AMBIENT_ENVIRONMENT = "ambient_environment"
    ENDPOINT_POLICY = "endpoint_policy"
    DNS_POLICY = "dns_policy"
    PEER_POLICY = "peer_policy"
    CA_BUNDLE_POLICY = "ca_bundle_policy"
    TLS_POLICY = "tls_policy"
    SESSION_POLICY = "session_policy"
    RETRY_POLICY = "retry_policy"
    WIRE_BOUND = "wire_bound"
    DECOMPRESSED_BOUND = "decompressed_bound"
    DECOMPRESSION = "decompression"
    SPOOL_POLICY = "spool_policy"
    TRANSPORT_RECORD = "transport_record"
    PARSER_RESOURCE_LIMIT = "parser_resource_limit"
    LIMITS_RECORD = "limits_record"


_GENERIC_ERRORS: Final[Mapping[BoundaryErrorCode, str]] = MappingProxyType(
    {
        BoundaryErrorCode.AMBIENT_ENVIRONMENT: "ambient network configuration rejected",
        BoundaryErrorCode.ENDPOINT_POLICY: "network endpoint rejected",
        BoundaryErrorCode.DNS_POLICY: "DNS response rejected",
        BoundaryErrorCode.PEER_POLICY: "connected peer rejected",
        BoundaryErrorCode.CA_BUNDLE_POLICY: "CA bundle rejected",
        BoundaryErrorCode.TLS_POLICY: "TLS policy rejected",
        BoundaryErrorCode.SESSION_POLICY: "HTTP session policy rejected",
        BoundaryErrorCode.RETRY_POLICY: "transport retry policy rejected",
        BoundaryErrorCode.WIRE_BOUND: "wire response bound exceeded",
        BoundaryErrorCode.DECOMPRESSED_BOUND: "decoded response bound exceeded",
        BoundaryErrorCode.DECOMPRESSION: "response decompression rejected",
        BoundaryErrorCode.SPOOL_POLICY: "response spool rejected",
        BoundaryErrorCode.TRANSPORT_RECORD: "transport evidence rejected",
        BoundaryErrorCode.PARSER_RESOURCE_LIMIT: "parser resource boundary rejected",
        BoundaryErrorCode.LIMITS_RECORD: "registered limits rejected",
    }
)


class NetworkBoundaryError(RuntimeError):
    """A generic boundary failure that never embeds hostile input or secrets."""

    def __init__(
        self,
        code: BoundaryErrorCode,
        *,
        wire_bytes: int = 0,
        decompressed_bytes: int = 0,
        wire_sha256: str | None = None,
        decompressed_sha256: str | None = None,
    ) -> None:
        self.code = code
        self.wire_bytes = wire_bytes
        self.decompressed_bytes = decompressed_bytes
        self.wire_sha256 = wire_sha256
        self.decompressed_sha256 = decompressed_sha256
        super().__init__(_GENERIC_ERRORS[code])


def _raise(code: BoundaryErrorCode) -> NoReturn:
    raise NetworkBoundaryError(code)


def reject_ambient_network_environment(
    environ: Mapping[str, str] | None = None,
) -> None:
    """Reject every registered ambient proxy/netrc/CA variable when non-empty."""

    source = os.environ if environ is None else environ
    for name in AMBIENT_NETWORK_ENVIRONMENT:
        value = source.get(name)
        if value is not None and (type(value) is not str or value != ""):
            _raise(BoundaryErrorCode.AMBIENT_ENVIRONMENT)


def _endpoint_policy(service: str) -> EndpointPolicy:
    if type(service) is not str or service not in ENDPOINT_POLICIES:
        _raise(BoundaryErrorCode.ENDPOINT_POLICY)
    return ENDPOINT_POLICIES[service]


def validate_endpoint(service: str, endpoint: str) -> EndpointPolicy:
    """Require the exact registered catalog endpoint for ``service``."""

    policy = _endpoint_policy(service)
    if type(endpoint) is not str or endpoint != policy.endpoint:
        _raise(BoundaryErrorCode.ENDPOINT_POLICY)
    return policy


_SAFE_ASYNC_PATH = re.compile(r"\A/[A-Za-z0-9._~/-]+\Z", re.ASCII)


def validate_async_job_url(service: str, job_url: str) -> str:
    """Accept only protocol-generated same-origin TAP async descendants."""

    policy = _endpoint_policy(service)
    if not policy.asynchronous or type(job_url) is not str:
        _raise(BoundaryErrorCode.ENDPOINT_POLICY)
    try:
        parsed = urlsplit(job_url)
        port = parsed.port
    except (TypeError, ValueError):
        _raise(BoundaryErrorCode.ENDPOINT_POLICY)
    if (
        parsed.scheme != "https"
        or parsed.hostname != policy.hostname
        or port not in (None, PEER_PORT)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query != ""
        or parsed.fragment != ""
        or parsed.path == ""
        or _SAFE_ASYNC_PATH.fullmatch(parsed.path) is None
        or "%" in parsed.path
        or "\\" in parsed.path
        or "//" in parsed.path
    ):
        _raise(BoundaryErrorCode.ENDPOINT_POLICY)
    prefix = f"{policy.path}/async/"
    if not parsed.path.startswith(prefix):
        _raise(BoundaryErrorCode.ENDPOINT_POLICY)
    relative = PurePosixPath(parsed.path[len(prefix) :])
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        _raise(BoundaryErrorCode.ENDPOINT_POLICY)
    return job_url


def _canonical_public_ip(value: str, code: BoundaryErrorCode) -> str:
    if type(value) is not str or value == "" or value.strip() != value:
        _raise(code)
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        _raise(code)
    if value != str(address):
        _raise(code)
    if (
        not address.is_global
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or address.is_private
    ):
        _raise(code)
    return str(address)


def validate_dns_answers(hostname: str, answers: Sequence[str]) -> tuple[str, ...]:
    """Validate all DNS answers; one non-public answer rejects the whole set."""

    if type(hostname) is not str or hostname not in ALLOWED_HOSTNAMES:
        _raise(BoundaryErrorCode.DNS_POLICY)
    if isinstance(answers, (str, bytes, bytearray)) or not isinstance(answers, Sequence):
        _raise(BoundaryErrorCode.DNS_POLICY)
    validated: list[str] = []
    seen: set[str] = set()
    for answer in answers:
        canonical = _canonical_public_ip(answer, BoundaryErrorCode.DNS_POLICY)
        if canonical not in seen:
            seen.add(canonical)
            validated.append(canonical)
    if not validated:
        _raise(BoundaryErrorCode.DNS_POLICY)
    return tuple(validated)


Resolver = Callable[..., list[tuple[Any, ...]]]


def resolve_public_addresses(
    hostname: str,
    *,
    resolver: Resolver | None = None,
) -> tuple[str, ...]:
    """Resolve an allow-listed host and fail if any returned peer is non-public."""

    if type(hostname) is not str or hostname not in ALLOWED_HOSTNAMES:
        _raise(BoundaryErrorCode.DNS_POLICY)
    resolve = socket.getaddrinfo if resolver is None else resolver
    try:
        results = resolve(
            hostname,
            PEER_PORT,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
        )
    except (OSError, TypeError, ValueError):
        _raise(BoundaryErrorCode.DNS_POLICY)
    answers: list[str] = []
    for result in results:
        if type(result) is not tuple or len(result) != 5:
            _raise(BoundaryErrorCode.DNS_POLICY)
        family, socktype, protocol, _canonname, sockaddr = result
        if family not in (socket.AF_INET, socket.AF_INET6):
            _raise(BoundaryErrorCode.DNS_POLICY)
        if socktype != socket.SOCK_STREAM or protocol not in (0, socket.IPPROTO_TCP):
            _raise(BoundaryErrorCode.DNS_POLICY)
        if type(sockaddr) is not tuple or len(sockaddr) < 2:
            _raise(BoundaryErrorCode.DNS_POLICY)
        if type(sockaddr[0]) is not str or type(sockaddr[1]) is not int:
            _raise(BoundaryErrorCode.DNS_POLICY)
        if sockaddr[1] != PEER_PORT:
            _raise(BoundaryErrorCode.DNS_POLICY)
        try:
            answers.append(str(ipaddress.ip_address(sockaddr[0])))
        except ValueError:
            _raise(BoundaryErrorCode.DNS_POLICY)
    return validate_dns_answers(hostname, answers)


@dataclass(frozen=True, slots=True)
class PeerEvidence:
    expected_hostname: str
    peer_ip: str
    peer_port: int
    tls_version: str
    leaf_certificate_sha256: str


def validate_connected_peer(
    *,
    expected_hostname: str,
    peer_ip: str,
    peer_port: int,
    validated_dns_answers: Sequence[str],
    tls_version: str,
    leaf_certificate_der: bytes,
) -> PeerEvidence:
    """Bind the connected TLS peer to the immediately preceding DNS answers."""

    if type(expected_hostname) is not str or expected_hostname not in ALLOWED_HOSTNAMES:
        _raise(BoundaryErrorCode.PEER_POLICY)
    dns_answers = validate_dns_answers(expected_hostname, validated_dns_answers)
    canonical = _canonical_public_ip(peer_ip, BoundaryErrorCode.PEER_POLICY)
    if type(peer_port) is not int or peer_port != PEER_PORT or canonical not in dns_answers:
        _raise(BoundaryErrorCode.PEER_POLICY)
    if type(tls_version) is not str or tls_version not in TLS_VERSIONS:
        _raise(BoundaryErrorCode.TLS_POLICY)
    if type(leaf_certificate_der) is not bytes or len(leaf_certificate_der) == 0:
        _raise(BoundaryErrorCode.TLS_POLICY)
    return PeerEvidence(
        expected_hostname=expected_hostname,
        peer_ip=canonical,
        peer_port=PEER_PORT,
        tls_version=TLS_VERSION,
        leaf_certificate_sha256=hashlib.sha256(leaf_certificate_der).hexdigest(),
    )


def tls_server_hostname(expected_hostname: str) -> str:
    """Return the exact allow-listed DNS name that must be supplied as SNI."""

    if type(expected_hostname) is not str or expected_hostname not in ALLOWED_HOSTNAMES:
        _raise(BoundaryErrorCode.TLS_POLICY)
    return expected_hostname


def _open_absolute_directory_no_symlinks(
    path: Path,
    *,
    error_code: BoundaryErrorCode,
) -> int:
    if not path.is_absolute():
        _raise(error_code)
    parts = path.parts
    if not parts or parts[0] != os.sep or any(part in ("", ".", "..") for part in parts[1:]):
        _raise(error_code)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = -1
    try:
        directory_fd = os.open(os.sep, flags)
        for component in parts[1:]:
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
    except OSError:
        if directory_fd >= 0:
            os.close(directory_fd)
        _raise(error_code)
    return directory_fd


def _open_parent_directory(path: Path) -> tuple[int, str]:
    if not path.is_absolute() or path.name in ("", ".", ".."):
        _raise(BoundaryErrorCode.CA_BUNDLE_POLICY)
    directory_fd = _open_absolute_directory_no_symlinks(
        path.parent,
        error_code=BoundaryErrorCode.CA_BUNDLE_POLICY,
    )
    return directory_fd, path.name


def load_registered_ca_bundle(path: str | Path) -> bytes:
    """Load the exact packaged CA bundle without following symlinks."""

    if not isinstance(path, (str, Path)):
        _raise(BoundaryErrorCode.CA_BUNDLE_POLICY)
    candidate = Path(path)
    if candidate.name != CA_BUNDLE_FILENAME:
        _raise(BoundaryErrorCode.CA_BUNDLE_POLICY)
    directory_fd, filename = _open_parent_directory(candidate)
    file_fd = -1
    try:
        file_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        metadata = os.fstat(file_fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size != CA_BUNDLE_BYTES
        ):
            _raise(BoundaryErrorCode.CA_BUNDLE_POLICY)
        chunks: list[bytes] = []
        remaining = CA_BUNDLE_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65_536, remaining))
            if chunk == b"":
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) != CA_BUNDLE_BYTES or hashlib.sha256(data).hexdigest() != CA_BUNDLE_SHA256:
            _raise(BoundaryErrorCode.CA_BUNDLE_POLICY)
        return data
    except NetworkBoundaryError:
        raise
    except OSError:
        _raise(BoundaryErrorCode.CA_BUNDLE_POLICY)
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(directory_fd)


def create_tls13_context(ca_bundle_path: str | Path) -> ssl.SSLContext:
    """Build the registered TLS context (v0.1.6: 1.2 floor, 1.3 ceiling, AEAD-only)."""

    reject_ambient_network_environment()
    if not hasattr(ssl.TLSVersion, "TLSv1_3") or not hasattr(ssl.TLSVersion, "TLSv1_2"):
        _raise(BoundaryErrorCode.TLS_POLICY)
    ca_bytes = load_registered_ca_bundle(ca_bundle_path)
    try:
        ca_text = ca_bytes.decode("ascii", errors="strict")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.set_ciphers(TLS12_AEAD_CIPHERS)
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.options |= ssl.OP_NO_COMPRESSION
        context.post_handshake_auth = False
        context.load_verify_locations(cadata=ca_text)
        context.set_alpn_protocols(["http/1.1"])
    except (UnicodeError, ValueError, ssl.SSLError):
        _raise(BoundaryErrorCode.TLS_POLICY)
    if (
        context.minimum_version is not ssl.TLSVersion.TLSv1_2
        or context.maximum_version is not ssl.TLSVersion.TLSv1_3
        or context.check_hostname is not True
        or context.verify_mode != ssl.CERT_REQUIRED
    ):
        _raise(BoundaryErrorCode.TLS_POLICY)
    return context


@dataclass(frozen=True, slots=True)
class HttpSessionPolicy:
    trust_env: bool
    redirects_max: int
    proxy_autodiscovery: bool
    netrc: bool
    ambient_cookies: bool
    os_keychain_client_identities: bool
    tls_client_certificates: bool
    anonymous_credentials: bool


HTTP_SESSION_POLICY: Final = HttpSessionPolicy(
    trust_env=False,
    redirects_max=0,
    proxy_autodiscovery=False,
    netrc=False,
    ambient_cookies=False,
    os_keychain_client_identities=False,
    tls_client_certificates=False,
    anonymous_credentials=True,
)
HTTP_SESSION_POLICY_FIELDS: Final = tuple(field.name for field in fields(HttpSessionPolicy))


def validate_http_session_policy(value: Mapping[str, object]) -> HttpSessionPolicy:
    """Validate an exact-key session-policy representation."""

    if not isinstance(value, Mapping) or tuple(value.keys()) != HTTP_SESSION_POLICY_FIELDS:
        _raise(BoundaryErrorCode.SESSION_POLICY)
    expected = {field: getattr(HTTP_SESSION_POLICY, field) for field in HTTP_SESSION_POLICY_FIELDS}
    for key, registered in expected.items():
        supplied = value[key]
        if type(supplied) is not type(registered) or supplied != registered:
            _raise(BoundaryErrorCode.SESSION_POLICY)
    return HTTP_SESSION_POLICY


@dataclass(frozen=True, slots=True)
class TransportTimingPolicy:
    tcp_connect_timeout_seconds: int = TCP_CONNECT_TIMEOUT_SECONDS
    tls_handshake_timeout_seconds: int = TLS_HANDSHAKE_TIMEOUT_SECONDS
    response_header_timeout_seconds: int = RESPONSE_HEADER_TIMEOUT_SECONDS
    body_read_timeout_seconds: int = BODY_READ_TIMEOUT_SECONDS
    gaia_logical_deadline_seconds: int = GAIA_LOGICAL_DEADLINE_SECONDS
    gaia_poll_interval_seconds: int = GAIA_POLL_INTERVAL_SECONDS
    gaia_poll_operations_max: int = GAIA_POLL_OPERATIONS_MAX
    simbad_logical_deadline_seconds: int = SIMBAD_LOGICAL_DEADLINE_SECONDS
    chen_logical_deadline_seconds: int = CHEN_LOGICAL_DEADLINE_SECONDS
    transport_attempts_max: int = TRANSPORT_ATTEMPTS_MAX
    retry_waits_seconds: tuple[int, int] = RETRY_WAITS_SECONDS
    redirects_max: int = REDIRECTS_MAX


TRANSPORT_TIMING_POLICY: Final = TransportTimingPolicy()


class FailureKind(str, Enum):
    CONNECTION_RESET = "connection_reset"
    TIMEOUT = "timeout"
    TLS_CLOSE_NOTIFY_LOSS = "tls_close_notify_loss"
    HTTP_STATUS = "http_status"
    SCHEMA = "schema"
    SHORT_PAGE = "short_page"
    BYTE_BOUND = "byte_bound"
    CERTIFICATE = "certificate"
    HOST = "host"
    REDIRECT = "redirect"
    OTHER = "other"


class RetryDisposition(str, Enum):
    RETRY = "retry"
    FATAL = "fatal"


@dataclass(frozen=True, slots=True)
class RetryDecision:
    disposition: RetryDisposition
    wait_seconds: int | None
    error_code: str


_RETRYABLE_HTTP_STATUSES: Final = frozenset({429, 502, 503, 504})
_PRE_RESPONSE_RETRYABLE: Final = frozenset(
    {
        FailureKind.CONNECTION_RESET,
        FailureKind.TIMEOUT,
        FailureKind.TLS_CLOSE_NOTIFY_LOSS,
    }
)


def classify_retry(
    *,
    failure_kind: FailureKind,
    operation_attempt: int,
    response_bytes_received: int,
    http_status: int | None = None,
) -> RetryDecision:
    """Apply the exact three-attempt, 5/15-second deterministic retry policy."""

    if (
        not isinstance(failure_kind, FailureKind)
        or type(operation_attempt) is not int
        or not 1 <= operation_attempt <= TRANSPORT_ATTEMPTS_MAX
        or type(response_bytes_received) is not int
        or response_bytes_received < 0
        or response_bytes_received > WIRE_BYTES_MAX
        or (http_status is not None and type(http_status) is not int)
    ):
        _raise(BoundaryErrorCode.RETRY_POLICY)

    retryable = False
    error_code = failure_kind.value
    if failure_kind in _PRE_RESPONSE_RETRYABLE:
        if http_status is not None:
            _raise(BoundaryErrorCode.RETRY_POLICY)
        if response_bytes_received > 0:
            return RetryDecision(RetryDisposition.FATAL, None, "response_after_bytes")
        retryable = True
    elif failure_kind is FailureKind.HTTP_STATUS:
        if http_status is None or not 100 <= http_status <= 599:
            _raise(BoundaryErrorCode.RETRY_POLICY)
        error_code = f"http_{http_status}"
        retryable = http_status in _RETRYABLE_HTTP_STATUSES
    elif http_status is not None:
        _raise(BoundaryErrorCode.RETRY_POLICY)

    if retryable and operation_attempt < TRANSPORT_ATTEMPTS_MAX:
        return RetryDecision(
            RetryDisposition.RETRY,
            RETRY_WAITS_SECONDS[operation_attempt - 1],
            error_code,
        )
    if retryable:
        return RetryDecision(RetryDisposition.FATAL, None, "retry_exhausted")
    return RetryDecision(RetryDisposition.FATAL, None, error_code)


@dataclass(frozen=True, slots=True)
class ResponseSpoolResult:
    path: Path
    wire_bytes: int
    decompressed_bytes: int
    wire_sha256: str
    decompressed_sha256: str
    content_encoding: str


def _safe_spool_filename(filename: str) -> bool:
    return (
        type(filename) is str
        and 0 < len(filename.encode("utf-8")) <= 180
        and filename not in (".", "..")
        and "/" not in filename
        and "\\" not in filename
        and "\x00" not in filename
    )


def _write_all(file_fd: int, data: bytes) -> None:
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        written = os.write(file_fd, view[offset:])
        if written <= 0:
            _raise(BoundaryErrorCode.SPOOL_POLICY)
        offset += written


def stream_response_to_spool(
    chunks: Iterable[bytes],
    *,
    attempt_directory: str | Path,
    filename: str,
    content_encoding: Literal["identity", "gzip"],
) -> ResponseSpoolResult:
    """Count/hash wire bytes and stream bounded decoded bytes to a 0600 spool."""

    if content_encoding not in ("identity", "gzip") or not _safe_spool_filename(filename):
        _raise(BoundaryErrorCode.SPOOL_POLICY)
    directory_path = Path(attempt_directory)
    if not directory_path.is_absolute():
        _raise(BoundaryErrorCode.SPOOL_POLICY)
    directory_fd = -1
    file_fd = -1
    wire_count = 0
    decoded_count = 0
    wire_hash = hashlib.sha256()
    decoded_hash = hashlib.sha256()
    decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16) if content_encoding == "gzip" else None

    def write_decoded(data: bytes) -> None:
        nonlocal decoded_count
        if decoded_count + len(data) > DECOMPRESSED_RESPONSE_BYTES_MAX:
            raise NetworkBoundaryError(
                BoundaryErrorCode.DECOMPRESSED_BOUND,
                wire_bytes=wire_count,
                decompressed_bytes=decoded_count + len(data),
                wire_sha256=wire_hash.hexdigest(),
                decompressed_sha256=decoded_hash.hexdigest(),
            )
        if data:
            _write_all(file_fd, data)
            decoded_hash.update(data)
            decoded_count += len(data)

    try:
        directory_fd = _open_absolute_directory_no_symlinks(
            directory_path,
            error_code=BoundaryErrorCode.SPOOL_POLICY,
        )
        directory_metadata = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or stat.S_IMODE(directory_metadata.st_mode) != 0o700
        ):
            _raise(BoundaryErrorCode.SPOOL_POLICY)
        file_fd = os.open(
            filename,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        os.fchmod(file_fd, 0o600)
        for chunk in chunks:
            if type(chunk) is not bytes:
                _raise(BoundaryErrorCode.SPOOL_POLICY)
            wire_count += len(chunk)
            wire_hash.update(chunk)
            if wire_count > WIRE_BYTES_MAX:
                raise NetworkBoundaryError(
                    BoundaryErrorCode.WIRE_BOUND,
                    wire_bytes=wire_count,
                    decompressed_bytes=decoded_count,
                    wire_sha256=wire_hash.hexdigest(),
                    decompressed_sha256=decoded_hash.hexdigest(),
                )
            if decompressor is None:
                write_decoded(chunk)
            else:
                pending = chunk
                while pending:
                    remaining = DECOMPRESSED_RESPONSE_BYTES_MAX - decoded_count
                    decoded = decompressor.decompress(pending, remaining + 1)
                    write_decoded(decoded)
                    if decompressor.unused_data:
                        _raise(BoundaryErrorCode.DECOMPRESSION)
                    next_pending = decompressor.unconsumed_tail
                    if next_pending == pending:
                        _raise(BoundaryErrorCode.DECOMPRESSION)
                    pending = next_pending
        if decompressor is not None:
            remaining = DECOMPRESSED_RESPONSE_BYTES_MAX - decoded_count
            write_decoded(decompressor.flush(remaining + 1))
            if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
                _raise(BoundaryErrorCode.DECOMPRESSION)
        os.fsync(file_fd)
        metadata = os.fstat(file_fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            _raise(BoundaryErrorCode.SPOOL_POLICY)
        return ResponseSpoolResult(
            path=directory_path / filename,
            wire_bytes=wire_count,
            decompressed_bytes=decoded_count,
            wire_sha256=wire_hash.hexdigest(),
            decompressed_sha256=decoded_hash.hexdigest(),
            content_encoding=content_encoding,
        )
    except NetworkBoundaryError:
        raise
    except (OSError, TypeError, ValueError):
        raise NetworkBoundaryError(
            BoundaryErrorCode.SPOOL_POLICY,
            wire_bytes=wire_count,
            decompressed_bytes=decoded_count,
            wire_sha256=wire_hash.hexdigest(),
            decompressed_sha256=decoded_hash.hexdigest(),
        ) from None
    except zlib.error:
        raise NetworkBoundaryError(
            BoundaryErrorCode.DECOMPRESSION,
            wire_bytes=wire_count,
            decompressed_bytes=decoded_count,
            wire_sha256=wire_hash.hexdigest(),
            decompressed_sha256=decoded_hash.hexdigest(),
        ) from None
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


TRANSPORT_ATTEMPT_COLUMNS: Final = (
    "attempt_id",
    "logical_request_id",
    "transport_ordinal",
    "phase",
    "started_at",
    "finished_at",
    "outcome",
    "http_status",
    "expected_hostname",
    "peer_ip",
    "peer_port",
    "leaf_certificate_sha256",
    "tls_version",
    "redirect_count",
    "wire_bytes",
    "decompressed_bytes",
    "wire_sha256",
    "decompressed_sha256",
    "error_code",
)
TRANSPORT_PHASES: Final = frozenset({"submit", "poll", "fetch", "sync"})
TRANSPORT_OUTCOMES: Final = frozenset({"success", "retryable_failure", "fatal_failure"})
TRANSPORT_ERROR_CODES: Final = frozenset(
    {
        "connection_reset",
        "timeout",
        "tls_close_notify_loss",
        "http_429",
        "http_502",
        "http_503",
        "http_504",
        "schema",
        "short_page",
        "byte_bound",
        "certificate",
        "host",
        "redirect",
        "response_after_bytes",
        "retry_exhausted",
        "decompression",
        "spool",
        "other",
    }
)
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z", re.ASCII)


def _strict_text(value: object, *, maximum_bytes: int = 4_096) -> str:
    if type(value) is not str or not 0 < len(value.encode("utf-8")) <= maximum_bytes:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    text = cast(str, value)
    if "\x00" in text:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    return text


def _strict_int(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    return cast(int, value)


def _strict_utc(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is not UTC:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    return cast(datetime, value)


def _uuid4(value: object) -> str:
    text = _strict_text(value, maximum_bytes=36)
    try:
        parsed = UUID(text)
    except ValueError:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    if parsed.version != 4 or str(parsed) != text:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    return text


@dataclass(frozen=True, slots=True)
class TransportAttemptRecord:
    attempt_id: str
    logical_request_id: str
    transport_ordinal: int
    phase: str
    started_at: datetime
    finished_at: datetime
    outcome: str
    http_status: int | None
    expected_hostname: str
    peer_ip: str
    peer_port: int
    leaf_certificate_sha256: str
    tls_version: str
    redirect_count: int
    wire_bytes: int
    decompressed_bytes: int
    wire_sha256: str
    decompressed_sha256: str
    error_code: str | None


def validate_transport_attempt(value: Mapping[str, object]) -> TransportAttemptRecord:
    """Validate one exact-order ``transport_attempts`` schema row."""

    if not isinstance(value, Mapping) or tuple(value.keys()) != TRANSPORT_ATTEMPT_COLUMNS:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    attempt_id = _uuid4(value["attempt_id"])
    logical_request_id = _strict_text(value["logical_request_id"])
    transport_ordinal = _strict_int(value["transport_ordinal"], minimum=1, maximum=10_000)
    phase = _strict_text(value["phase"], maximum_bytes=16)
    if phase not in TRANSPORT_PHASES:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    started_at = _strict_utc(value["started_at"])
    finished_at = _strict_utc(value["finished_at"])
    if finished_at < started_at:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    outcome = _strict_text(value["outcome"], maximum_bytes=32)
    if outcome not in TRANSPORT_OUTCOMES:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    status_value = value["http_status"]
    http_status = (
        None if status_value is None else _strict_int(status_value, minimum=100, maximum=599)
    )
    expected_hostname = _strict_text(value["expected_hostname"], maximum_bytes=128)
    if expected_hostname not in ALLOWED_HOSTNAMES:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    peer_ip = _canonical_public_ip(
        _strict_text(value["peer_ip"], maximum_bytes=64),
        BoundaryErrorCode.TRANSPORT_RECORD,
    )
    peer_port = _strict_int(value["peer_port"], minimum=PEER_PORT, maximum=PEER_PORT)
    leaf_hash = _strict_text(value["leaf_certificate_sha256"], maximum_bytes=64)
    tls_version = _strict_text(value["tls_version"], maximum_bytes=16)
    redirect_count = _strict_int(value["redirect_count"], minimum=0, maximum=0)
    wire_bytes = _strict_int(value["wire_bytes"], minimum=0, maximum=WIRE_BYTES_MAX)
    decoded_bytes = _strict_int(
        value["decompressed_bytes"],
        minimum=0,
        maximum=DECOMPRESSED_RESPONSE_BYTES_MAX,
    )
    wire_hash = _strict_text(value["wire_sha256"], maximum_bytes=64)
    decoded_hash = _strict_text(value["decompressed_sha256"], maximum_bytes=64)
    if (
        _HEX64.fullmatch(leaf_hash) is None
        or tls_version not in TLS_VERSIONS
        or _HEX64.fullmatch(wire_hash) is None
        or _HEX64.fullmatch(decoded_hash) is None
    ):
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    error_value = value["error_code"]
    error_code = None if error_value is None else _strict_text(error_value, maximum_bytes=64)
    if outcome == "success":
        if error_code is not None:
            _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    elif error_code not in TRANSPORT_ERROR_CODES:
        _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    if outcome == "retryable_failure":
        if error_code not in {
            "connection_reset",
            "timeout",
            "tls_close_notify_loss",
            "http_429",
            "http_502",
            "http_503",
            "http_504",
        }:
            _raise(BoundaryErrorCode.TRANSPORT_RECORD)
        retry_error = cast(str, error_code)
        if retry_error.startswith("http_"):
            if http_status != int(retry_error.removeprefix("http_")):
                _raise(BoundaryErrorCode.TRANSPORT_RECORD)
        elif wire_bytes != 0:
            _raise(BoundaryErrorCode.TRANSPORT_RECORD)
    return TransportAttemptRecord(
        attempt_id,
        logical_request_id,
        transport_ordinal,
        phase,
        started_at,
        finished_at,
        outcome,
        http_status,
        expected_hostname,
        peer_ip,
        peer_port,
        leaf_hash,
        tls_version,
        redirect_count,
        wire_bytes,
        decoded_bytes,
        wire_hash,
        decoded_hash,
        error_code,
    )


def _resource_module() -> ModuleType:
    return importlib.import_module("resource")


def establish_parser_address_space_limit() -> None:
    """Set/read back the exact 1 GiB hard ``RLIMIT_AS`` before parser imports."""

    if any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in sys.modules
        for prefix in ("pyarrow", "astropy")
    ):
        _raise(BoundaryErrorCode.PARSER_RESOURCE_LIMIT)
    try:
        resource = _resource_module()
        limit_id = getattr(resource, "RLIMIT_AS")
        setrlimit = getattr(resource, "setrlimit")
        getrlimit = getattr(resource, "getrlimit")
        if type(limit_id) is not int or not callable(setrlimit) or not callable(getrlimit):
            _raise(BoundaryErrorCode.PARSER_RESOURCE_LIMIT)
        registered = (PARSER_ADDRESS_SPACE_BYTES_MAX, PARSER_ADDRESS_SPACE_BYTES_MAX)
        setrlimit(limit_id, registered)
        readback = getrlimit(limit_id)
    except NetworkBoundaryError:
        raise
    except (AttributeError, OSError, TypeError, ValueError):
        _raise(BoundaryErrorCode.PARSER_RESOURCE_LIMIT)
    if type(readback) is not tuple or readback != registered:
        _raise(BoundaryErrorCode.PARSER_RESOURCE_LIMIT)


def apply_best_effort_address_space_limit() -> bool:
    """Frozen v0.1.7 Section 2: platform defense applied when accepted.

    The 1 GiB hard RLIMIT_AS is applied and read back exactly when the
    platform accepts it; a platform refusal is recorded (return False) and is
    not fatal. The mandatory containment is the bounded parser allocator and
    the registered byte caps, which this function does not weaken.
    """
    import resource as _resource

    registered = (PARSER_ADDRESS_SPACE_BYTES_MAX, PARSER_ADDRESS_SPACE_BYTES_MAX)
    try:
        _resource.setrlimit(_resource.RLIMIT_AS, registered)
        readback = _resource.getrlimit(_resource.RLIMIT_AS)
    except (OSError, ValueError):
        return False
    return readback == registered


_LIMITS_ITEMS: Final[tuple[tuple[str, object], ...]] = (
    ("source_batch_rows", 500),
    ("simbad_matches_per_source_catalog", 100),
    ("simbad_maxrec", 50_001),
    ("chen_rows_exclusive_max", 10_000),
    ("cli_source_ids_max", 10_000),
    ("raw_candidate_rows_max", 250_000),
    ("final_control_rows_min", 50_000),
    ("final_control_rows_max", 250_000),
    ("exclusion_rows_max", 5_000_000),
    ("wire_bytes_max", WIRE_BYTES_MAX),
    ("decompressed_response_bytes_max", DECOMPRESSED_RESPONSE_BYTES_MAX),
    ("deep_table_bytes_max", 134_217_728),
    ("live_response_table_bytes_max", 268_435_456),
    ("process_rss_bytes_max", PROCESS_RSS_BYTES_MAX),
    ("yaml_bytes_max", 1_048_576),
    ("parquet_file_bytes_max", 2_147_483_648),
    ("parquet_footer_bytes_max", 16_777_216),
    ("parquet_metadata_bytes_max", 1_048_576),
    ("parquet_columns_max", 64),
    ("parquet_row_groups_max", 1_024),
    ("parquet_nesting_depth_max", 0),
    ("parquet_column_chunk_compressed_bytes_max", 67_108_864),
    ("parquet_column_chunk_uncompressed_bytes_max", 134_217_728),
    ("parquet_data_page_compressed_bytes_max", 16_777_216),
    ("parquet_data_page_uncompressed_bytes_max", 33_554_432),
    ("parquet_page_header_bytes_max", 65_536),
    ("parser_allocator_bytes_max", PARSER_ALLOCATOR_BYTES_MAX),
    ("parser_address_space_bytes_max", PARSER_ADDRESS_SPACE_BYTES_MAX),
    ("text_scalar_bytes_max", 4_096),
    ("catalog_text_bytes_max", 512),
    ("query_bytes_max", 65_536),
    ("decoded_string_bytes_max", 33_554_432),
    ("release_files_max", 2_048),
    ("release_tree_bytes_max", 4_294_967_296),
    ("relative_path_bytes_max", 240),
    ("filename_component_bytes_max", 180),
    ("logical_catalog_requests_max", 231),
    ("tcp_connect_timeout_seconds", TCP_CONNECT_TIMEOUT_SECONDS),
    ("tls_handshake_timeout_seconds", TLS_HANDSHAKE_TIMEOUT_SECONDS),
    ("response_header_timeout_seconds", RESPONSE_HEADER_TIMEOUT_SECONDS),
    ("body_read_timeout_seconds", BODY_READ_TIMEOUT_SECONDS),
    ("gaia_logical_deadline_seconds", GAIA_LOGICAL_DEADLINE_SECONDS),
    ("gaia_poll_interval_seconds", GAIA_POLL_INTERVAL_SECONDS),
    ("gaia_poll_operations_max", GAIA_POLL_OPERATIONS_MAX),
    ("simbad_logical_deadline_seconds", SIMBAD_LOGICAL_DEADLINE_SECONDS),
    ("chen_logical_deadline_seconds", CHEN_LOGICAL_DEADLINE_SECONDS),
    ("transport_attempts_max", TRANSPORT_ATTEMPTS_MAX),
    ("retry_wait_1_seconds", RETRY_WAITS_SECONDS[0]),
    ("retry_wait_2_seconds", RETRY_WAITS_SECONDS[1]),
    ("redirects_max", REDIRECTS_MAX),
    ("peer_port", PEER_PORT),
    ("ca_bundle_bytes", CA_BUNDLE_BYTES),
    ("tls_version_min", TLS_VERSION_MIN),
    ("tls_version_max", TLS_VERSION_MAX),
    ("ca_bundle_sha256", CA_BUNDLE_SHA256),
    ("allowed_hostnames", ALLOWED_HOSTNAMES),
)
LIMITS_RECORD_FIELDS: Final = tuple(name for name, _value in _LIMITS_ITEMS)


def registered_limits_record() -> dict[str, object]:
    """Return a new exact-order manifest ``LimitsRecord`` mapping."""

    record: dict[str, object] = {}
    for name, value in _LIMITS_ITEMS:
        if name == "allowed_hostnames":
            record[name] = list(cast(tuple[str, ...], value))
        else:
            record[name] = value
    return record


def validate_limits_record(value: Mapping[str, object]) -> dict[str, object]:
    """Reject any missing, extra, reordered, mistyped, or unequal limit."""

    if not isinstance(value, Mapping) or tuple(value.keys()) != LIMITS_RECORD_FIELDS:
        _raise(BoundaryErrorCode.LIMITS_RECORD)
    expected = registered_limits_record()
    for key in LIMITS_RECORD_FIELDS:
        supplied = value[key]
        registered = expected[key]
        if key == "allowed_hostnames":
            if type(supplied) is not list or supplied != registered:
                _raise(BoundaryErrorCode.LIMITS_RECORD)
        elif type(supplied) is not type(registered) or supplied != registered:
            _raise(BoundaryErrorCode.LIMITS_RECORD)
    return cast(dict[str, object], expected)
