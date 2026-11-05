"""Adversarial tests for the frozen v0.1.4 network/parser boundary."""

from __future__ import annotations

import gzip
import hashlib
import os
import socket
import ssl
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import certifi
import pytest

from pharos import control_network_v014 as network


def _clear_ambient(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in network.AMBIENT_NETWORK_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def _clear_parser_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(sys.modules):
        if name in {"pyarrow", "astropy"} or name.startswith(("pyarrow.", "astropy.")):
            monkeypatch.delitem(sys.modules, name)


def _copy_registered_ca(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    source = Path(certifi.where())
    target = tmp_path / network.CA_BUNDLE_FILENAME
    target.write_bytes(source.read_bytes())
    target.chmod(0o600)
    return target


def _valid_transport_row() -> dict[str, object]:
    now = datetime(2026, 8, 6, 12, 0, 0, 123456, tzinfo=UTC)
    empty_hash = hashlib.sha256(b"").hexdigest()
    return {
        "attempt_id": "4d36e968-e325-4b1a-94c8-70906dbfc53c",
        "logical_request_id": "gaia-0000",
        "transport_ordinal": 1,
        "phase": "submit",
        "started_at": now,
        "finished_at": now + timedelta(microseconds=1),
        "outcome": "success",
        "http_status": 200,
        "expected_hostname": "gea.esac.esa.int",
        "peer_ip": "8.8.8.8",
        "peer_port": 443,
        "leaf_certificate_sha256": hashlib.sha256(b"certificate").hexdigest(),
        "tls_version": "TLSv1.3",
        "redirect_count": 0,
        "wire_bytes": 0,
        "decompressed_bytes": 0,
        "wire_sha256": empty_hash,
        "decompressed_sha256": empty_hash,
        "error_code": None,
    }


def test_frozen_identity_endpoints_timeouts_and_resource_constants_are_exact() -> None:
    assert network.PREREGISTRATION_BYTES == 4_936
    assert network.PREREGISTRATION_SHA256 == (
        "9c1751721a2021c632a8a86cfab6a67e1f23e1bcc84973a25dc156b2b5bc7999"
    )
    assert tuple(network.ENDPOINT_POLICIES) == ("gaia", "simbad", "chen")
    assert [policy.endpoint for policy in network.ENDPOINT_POLICIES.values()] == [
        "https://gea.esac.esa.int/tap-server/tap",
        "https://simbad.cds.unistra.fr/simbad/sim-tap",
        "https://vizier.cds.unistra.fr/viz-bin/votable",
    ]
    assert network.ALLOWED_HOSTNAMES == (
        "gea.esac.esa.int",
        "simbad.cds.unistra.fr",
        "vizier.cds.unistra.fr",
    )
    assert network.TRANSPORT_TIMING_POLICY == network.TransportTimingPolicy(
        tcp_connect_timeout_seconds=10,
        tls_handshake_timeout_seconds=10,
        response_header_timeout_seconds=60,
        body_read_timeout_seconds=600,
        gaia_logical_deadline_seconds=7_200,
        gaia_poll_interval_seconds=10,
        gaia_poll_operations_max=720,
        simbad_logical_deadline_seconds=600,
        chen_logical_deadline_seconds=600,
        transport_attempts_max=3,
        retry_waits_seconds=(5, 15),
        redirects_max=0,
    )
    limits = network.registered_limits_record()
    assert tuple(limits) == network.LIMITS_RECORD_FIELDS
    assert limits["wire_bytes_max"] == 33_554_432
    assert limits["decompressed_response_bytes_max"] == 67_108_864
    assert limits["parser_allocator_bytes_max"] == 268_435_456
    assert limits["parser_address_space_bytes_max"] == 1_073_741_824
    assert limits["ca_bundle_bytes"] == 234_072
    assert limits["ca_bundle_sha256"] == network.CA_BUNDLE_SHA256
    assert limits["allowed_hostnames"] == list(network.ALLOWED_HOSTNAMES)
    assert network.validate_limits_record(limits) == limits


@pytest.mark.parametrize("mutation", ["missing", "extra", "reordered", "bool", "changed"])
def test_limits_record_rejects_shape_type_order_and_value_drift(mutation: str) -> None:
    limits = network.registered_limits_record()
    if mutation == "missing":
        limits.pop("source_batch_rows")
    elif mutation == "extra":
        limits["unexpected"] = 1
    elif mutation == "reordered":
        first = limits.pop("source_batch_rows")
        limits["source_batch_rows"] = first
    elif mutation == "bool":
        limits["source_batch_rows"] = True
    else:
        limits["source_batch_rows"] = 501
    with pytest.raises(network.NetworkBoundaryError) as raised:
        network.validate_limits_record(limits)
    assert raised.value.code is network.BoundaryErrorCode.LIMITS_RECORD


@pytest.mark.parametrize(
    ("service", "endpoint"),
    [
        ("gaia", "http://gea.esac.esa.int/tap-server/tap"),
        ("gaia", "https://gea.esac.esa.int:444/tap-server/tap"),
        ("gaia", "https://gea.esac.esa.int/tap-server/tap?x=1"),
        ("simbad", "https://simbad.cds.unistra.fr/simbad/sim-tap/"),
        ("chen", "https://vizier.cds.unistra.fr/viz-bin/votable#x"),
        ("unknown", "https://gea.esac.esa.int/tap-server/tap"),
    ],
)
def test_endpoint_allowlist_is_exact(service: str, endpoint: str) -> None:
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_endpoint(service, endpoint)


def test_exact_endpoints_and_same_origin_async_job_urls_pass() -> None:
    assert (
        network.validate_endpoint("gaia", "https://gea.esac.esa.int/tap-server/tap").hostname
        == "gea.esac.esa.int"
    )
    assert network.validate_async_job_url(
        "gaia", "https://gea.esac.esa.int/tap-server/tap/async/abc-123/phase"
    ).endswith("/phase")
    assert network.validate_async_job_url(
        "simbad", "https://simbad.cds.unistra.fr:443/simbad/sim-tap/async/abc"
    ).endswith("/abc")


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.invalid/tap-server/tap/async/abc",
        "https://user@gea.esac.esa.int/tap-server/tap/async/abc",
        "https://gea.esac.esa.int/tap-server/tap/async/../secret",
        "https://gea.esac.esa.int/tap-server/tap/async/%2e%2e/secret",
        "https://gea.esac.esa.int/tap-server/tap/async//secret",
        "https://gea.esac.esa.int/tap-server/tap/async/abc?redirect=evil",
        "https://gea.esac.esa.int:444/tap-server/tap/async/abc",
    ],
)
def test_async_job_url_rejects_cross_origin_credentials_and_path_confusion(url: str) -> None:
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_async_job_url("gaia", url)
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_async_job_url(
            "chen", "https://vizier.cds.unistra.fr/viz-bin/votable/async/abc"
        )


def test_every_registered_ambient_variable_fails_when_nonempty_without_value_leak() -> None:
    secret = "http://secret-token@example.invalid"
    for name in network.AMBIENT_NETWORK_ENVIRONMENT:
        with pytest.raises(network.NetworkBoundaryError) as raised:
            network.reject_ambient_network_environment({name: secret})
        assert raised.value.code is network.BoundaryErrorCode.AMBIENT_ENVIRONMENT
        assert secret not in str(raised.value)
        network.reject_ambient_network_environment({name: ""})


def test_http_session_policy_is_exact_key_order_and_trust_env_false() -> None:
    policy = network.HTTP_SESSION_POLICY
    assert policy.trust_env is False
    assert policy.redirects_max == 0
    assert policy.proxy_autodiscovery is False
    assert policy.netrc is False
    assert policy.ambient_cookies is False
    assert policy.os_keychain_client_identities is False
    assert policy.tls_client_certificates is False
    representation = {field: getattr(policy, field) for field in network.HTTP_SESSION_POLICY_FIELDS}
    assert network.validate_http_session_policy(representation) is policy

    representation["trust_env"] = True
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_http_session_policy(representation)
    reordered = {key: getattr(policy, key) for key in reversed(network.HTTP_SESSION_POLICY_FIELDS)}
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_http_session_policy(reordered)
    representation = {field: getattr(policy, field) for field in network.HTTP_SESSION_POLICY_FIELDS}
    representation["extra"] = False
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_http_session_policy(representation)


def test_registered_ca_bundle_builds_tls13_only_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_ambient(monkeypatch)
    ca_path = _copy_registered_ca(tmp_path)
    data = network.load_registered_ca_bundle(ca_path)
    assert len(data) == 234_072
    assert hashlib.sha256(data).hexdigest() == network.CA_BUNDLE_SHA256

    context = network.create_tls13_context(ca_path)
    assert context.minimum_version is ssl.TLSVersion.TLSv1_2
    assert context.maximum_version is ssl.TLSVersion.TLSv1_3
    assert all(
        "CBC" not in cipher and "RC4" not in cipher
        for cipher in context.get_ciphers()
    )
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.options & ssl.OP_NO_COMPRESSION
    assert context.cert_store_stats()["x509_ca"] > 0


def test_ca_bundle_rejects_wrong_name_size_digest_symlink_and_hardlink(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    wrong_name = tmp_path / "cacert.pem"
    wrong_name.write_bytes(Path(certifi.where()).read_bytes())
    with pytest.raises(network.NetworkBoundaryError):
        network.load_registered_ca_bundle(wrong_name)

    target = tmp_path / network.CA_BUNDLE_FILENAME
    target.write_bytes(b"malicious CA material")
    with pytest.raises(network.NetworkBoundaryError) as raised:
        network.load_registered_ca_bundle(target)
    assert "malicious CA material" not in str(raised.value)
    target.unlink()

    real = tmp_path / "real.pem"
    real.write_bytes(Path(certifi.where()).read_bytes())
    target.symlink_to(real)
    with pytest.raises(network.NetworkBoundaryError):
        network.load_registered_ca_bundle(target)
    target.unlink()

    os.link(real, target)
    with pytest.raises(network.NetworkBoundaryError):
        network.load_registered_ca_bundle(target)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.1.1",
        "224.0.0.1",
        "0.0.0.0",
        "192.0.2.1",
        "::1",
        "fe80::1",
        "ff02::1",
        "::",
        "2001:db8::1",
        "2606:4700:4700:0:0:0:0:1111",
    ],
)
def test_dns_rejects_nonpublic_and_noncanonical_answers(address: str) -> None:
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_dns_answers("gea.esac.esa.int", [address])


def test_dns_and_connected_peer_require_public_answer_membership_and_tls13() -> None:
    answers = network.validate_dns_answers(
        "gea.esac.esa.int", ["8.8.8.8", "2606:4700:4700::1111", "8.8.8.8"]
    )
    assert answers == ("8.8.8.8", "2606:4700:4700::1111")
    evidence = network.validate_connected_peer(
        expected_hostname="gea.esac.esa.int",
        peer_ip="8.8.8.8",
        peer_port=443,
        validated_dns_answers=answers,
        tls_version="TLSv1.3",
        leaf_certificate_der=b"leaf certificate",
    )
    assert evidence.peer_ip == "8.8.8.8"
    assert evidence.leaf_certificate_sha256 == hashlib.sha256(b"leaf certificate").hexdigest()
    assert network.tls_server_hostname("gea.esac.esa.int") == "gea.esac.esa.int"
    with pytest.raises(network.NetworkBoundaryError):
        network.tls_server_hostname("8.8.8.8")

    for mutation in (
        {"peer_ip": "1.1.1.1"},
        {"peer_ip": "127.0.0.1"},
        {"peer_port": 80},
        {"tls_version": "TLSv1.0"},
        {"leaf_certificate_der": b""},
    ):
        arguments: dict[str, Any] = {
            "expected_hostname": "gea.esac.esa.int",
            "peer_ip": "8.8.8.8",
            "peer_port": 443,
            "validated_dns_answers": answers,
            "tls_version": "TLSv1.3",
            "leaf_certificate_der": b"leaf certificate",
        }
        arguments.update(mutation)
        with pytest.raises(network.NetworkBoundaryError):
            network.validate_connected_peer(**arguments)


def test_resolver_validates_every_returned_answer_without_live_dns() -> None:
    def valid_resolver(*_args: object) -> list[tuple[Any, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2606:4700:4700::1111", 443, 0, 0),
            ),
        ]

    assert network.resolve_public_addresses("gea.esac.esa.int", resolver=valid_resolver) == (
        "8.8.8.8",
        "2606:4700:4700::1111",
    )

    def mixed_resolver(*_args: object) -> list[tuple[Any, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.1", 443)),
        ]

    with pytest.raises(network.NetworkBoundaryError):
        network.resolve_public_addresses("gea.esac.esa.int", resolver=mixed_resolver)


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_retryable_http_statuses_use_exact_waits_and_attempt_bound(status: int) -> None:
    first = network.classify_retry(
        failure_kind=network.FailureKind.HTTP_STATUS,
        operation_attempt=1,
        response_bytes_received=0,
        http_status=status,
    )
    second = network.classify_retry(
        failure_kind=network.FailureKind.HTTP_STATUS,
        operation_attempt=2,
        response_bytes_received=100,
        http_status=status,
    )
    exhausted = network.classify_retry(
        failure_kind=network.FailureKind.HTTP_STATUS,
        operation_attempt=3,
        response_bytes_received=0,
        http_status=status,
    )
    assert (first.disposition, first.wait_seconds) == (network.RetryDisposition.RETRY, 5)
    assert (second.disposition, second.wait_seconds) == (network.RetryDisposition.RETRY, 15)
    assert exhausted == network.RetryDecision(
        network.RetryDisposition.FATAL, None, "retry_exhausted"
    )


@pytest.mark.parametrize(
    "kind",
    [
        network.FailureKind.CONNECTION_RESET,
        network.FailureKind.TIMEOUT,
        network.FailureKind.TLS_CLOSE_NOTIFY_LOSS,
    ],
)
def test_pre_response_transport_failures_retry_but_response_after_bytes_is_fatal(
    kind: network.FailureKind,
) -> None:
    assert (
        network.classify_retry(
            failure_kind=kind,
            operation_attempt=1,
            response_bytes_received=0,
        ).wait_seconds
        == 5
    )
    after_bytes = network.classify_retry(
        failure_kind=kind,
        operation_attempt=1,
        response_bytes_received=1,
    )
    assert after_bytes == network.RetryDecision(
        network.RetryDisposition.FATAL, None, "response_after_bytes"
    )


def test_schema_redirect_certificate_and_unregistered_http_errors_are_fatal() -> None:
    for kind in (
        network.FailureKind.SCHEMA,
        network.FailureKind.SHORT_PAGE,
        network.FailureKind.BYTE_BOUND,
        network.FailureKind.CERTIFICATE,
        network.FailureKind.HOST,
        network.FailureKind.REDIRECT,
        network.FailureKind.OTHER,
    ):
        decision = network.classify_retry(
            failure_kind=kind,
            operation_attempt=1,
            response_bytes_received=0,
        )
        assert decision.disposition is network.RetryDisposition.FATAL
        assert decision.wait_seconds is None
    assert (
        network.classify_retry(
            failure_kind=network.FailureKind.HTTP_STATUS,
            operation_attempt=1,
            response_bytes_received=0,
            http_status=500,
        ).disposition
        is network.RetryDisposition.FATAL
    )


def test_streaming_spool_hashes_identity_and_gzip_and_uses_strict_modes(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir(mode=0o700)
    identity = network.stream_response_to_spool(
        [b"abc", b"", b"def"],
        attempt_directory=attempt,
        filename="identity.spool",
        content_encoding="identity",
    )
    assert identity.path.read_bytes() == b"abcdef"
    assert identity.wire_bytes == identity.decompressed_bytes == 6
    assert identity.wire_sha256 == hashlib.sha256(b"abcdef").hexdigest()
    assert identity.decompressed_sha256 == hashlib.sha256(b"abcdef").hexdigest()
    assert identity.path.stat().st_mode & 0o777 == 0o600

    payload = b"bounded decoded response" * 100
    compressed = gzip.compress(payload, mtime=0)
    decoded = network.stream_response_to_spool(
        [compressed[:7], compressed[7:]],
        attempt_directory=attempt,
        filename="gzip.spool",
        content_encoding="gzip",
    )
    assert decoded.path.read_bytes() == payload
    assert decoded.wire_bytes == len(compressed)
    assert decoded.decompressed_bytes == len(payload)
    assert decoded.wire_sha256 == hashlib.sha256(compressed).hexdigest()
    assert decoded.decompressed_sha256 == hashlib.sha256(payload).hexdigest()


def test_streaming_spool_fails_closed_on_bounds_malformed_streams_and_bad_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir(mode=0o700)
    monkeypatch.setattr(network, "WIRE_BYTES_MAX", 4)
    with pytest.raises(network.NetworkBoundaryError) as wire:
        network.stream_response_to_spool(
            [b"123", b"45"],
            attempt_directory=attempt,
            filename="wire.spool",
            content_encoding="identity",
        )
    assert wire.value.code is network.BoundaryErrorCode.WIRE_BOUND

    monkeypatch.setattr(network, "WIRE_BYTES_MAX", 33_554_432)
    monkeypatch.setattr(network, "DECOMPRESSED_RESPONSE_BYTES_MAX", 4)
    with pytest.raises(network.NetworkBoundaryError) as decoded:
        network.stream_response_to_spool(
            [gzip.compress(b"12345", mtime=0)],
            attempt_directory=attempt,
            filename="decoded.spool",
            content_encoding="gzip",
        )
    assert decoded.value.code is network.BoundaryErrorCode.DECOMPRESSED_BOUND

    monkeypatch.setattr(network, "DECOMPRESSED_RESPONSE_BYTES_MAX", 67_108_864)
    for filename, payload in (
        ("truncated.spool", gzip.compress(b"content", mtime=0)[:-2]),
        ("members.spool", gzip.compress(b"one", mtime=0) + gzip.compress(b"two", mtime=0)),
        ("malformed.spool", b"untrusted payload secret"),
    ):
        with pytest.raises(network.NetworkBoundaryError) as malformed:
            network.stream_response_to_spool(
                [payload],
                attempt_directory=attempt,
                filename=filename,
                content_encoding="gzip",
            )
        assert "untrusted payload secret" not in str(malformed.value)

    wrong_mode = tmp_path / "wrong-mode"
    wrong_mode.mkdir(mode=0o755)
    with pytest.raises(network.NetworkBoundaryError):
        network.stream_response_to_spool(
            [b"data"],
            attempt_directory=wrong_mode,
            filename="response.spool",
            content_encoding="identity",
        )
    real_attempt = tmp_path / "real-attempt"
    real_attempt.mkdir(mode=0o700)
    linked_attempt = tmp_path / "linked-attempt"
    linked_attempt.symlink_to(real_attempt, target_is_directory=True)
    with pytest.raises(network.NetworkBoundaryError):
        network.stream_response_to_spool(
            [b"data"],
            attempt_directory=linked_attempt,
            filename="response.spool",
            content_encoding="identity",
        )
    with pytest.raises(network.NetworkBoundaryError):
        network.stream_response_to_spool(
            [b"data"],
            attempt_directory=attempt,
            filename="../escape",
            content_encoding="identity",
        )
    with pytest.raises(network.NetworkBoundaryError):
        network.stream_response_to_spool(
            [bytearray(b"data")],  # type: ignore[list-item]
            attempt_directory=attempt,
            filename="mutable.spool",
            content_encoding="identity",
        )


def test_transport_attempt_exact_schema_accepts_valid_record() -> None:
    row = _valid_transport_row()
    record = network.validate_transport_attempt(row)
    assert tuple(row) == network.TRANSPORT_ATTEMPT_COLUMNS
    assert record.transport_ordinal == 1
    assert record.peer_ip == "8.8.8.8"
    assert record.redirect_count == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transport_ordinal", True),
        ("transport_ordinal", 0),
        ("phase", "download"),
        ("started_at", datetime(2026, 8, 6)),
        ("outcome", "maybe"),
        ("http_status", True),
        ("http_status", 99),
        ("expected_hostname", "evil.invalid"),
        ("peer_ip", "127.0.0.1"),
        ("peer_ip", "2606:4700:4700:0:0:0:0:1111"),
        ("peer_port", 80),
        ("leaf_certificate_sha256", "A" * 64),
        ("tls_version", "TLSv1.0"),
        ("redirect_count", 1),
        ("wire_bytes", 33_554_433),
        ("decompressed_bytes", 67_108_865),
        ("wire_sha256", "0" * 63),
        ("error_code", "remote payload details"),
    ],
)
def test_transport_attempt_rejects_wrong_types_domains_and_evidence(
    field: str, value: object
) -> None:
    row = _valid_transport_row()
    row[field] = value
    with pytest.raises(network.NetworkBoundaryError) as raised:
        network.validate_transport_attempt(row)
    assert raised.value.code is network.BoundaryErrorCode.TRANSPORT_RECORD
    assert "remote payload details" not in str(raised.value)


def test_transport_attempt_rejects_missing_extra_reordered_and_bad_failure_relations() -> None:
    row = _valid_transport_row()
    row.pop("phase")
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_transport_attempt(row)

    row = _valid_transport_row()
    row["extra"] = "value"
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_transport_attempt(row)

    row = _valid_transport_row()
    phase = row.pop("phase")
    row["phase"] = phase
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_transport_attempt(row)

    row = _valid_transport_row()
    row["outcome"] = "retryable_failure"
    row["error_code"] = "timeout"
    row["wire_bytes"] = 1
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_transport_attempt(row)

    row = _valid_transport_row()
    row["outcome"] = "retryable_failure"
    row["error_code"] = "http_503"
    row["http_status"] = 502
    with pytest.raises(network.NetworkBoundaryError):
        network.validate_transport_attempt(row)


class _FakeResource(ModuleType):
    def __init__(self, *, readback: tuple[int, int] | None = None) -> None:
        super().__init__("resource")
        self.RLIMIT_AS = 5
        self.calls: list[tuple[int, tuple[int, int]]] = []
        self.readback = readback

    def setrlimit(self, resource_id: int, limits: tuple[int, int]) -> None:
        self.calls.append((resource_id, limits))

    def getrlimit(self, resource_id: int) -> tuple[int, int]:
        assert resource_id == self.RLIMIT_AS
        if self.readback is not None:
            return self.readback
        return self.calls[-1][1]


def test_parser_worker_sets_and_reads_back_exact_hard_rlimit_before_parser_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeResource()
    monkeypatch.setattr(network, "_resource_module", lambda: fake)
    _clear_parser_modules(monkeypatch)
    network.establish_parser_address_space_limit()
    assert fake.calls == [(5, (1_073_741_824, 1_073_741_824))]


def test_parser_worker_fails_when_primitive_or_exact_readback_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = ModuleType("resource")
    monkeypatch.setattr(network, "_resource_module", lambda: missing)
    _clear_parser_modules(monkeypatch)
    with pytest.raises(network.NetworkBoundaryError):
        network.establish_parser_address_space_limit()

    mismatch = _FakeResource(readback=(1_073_741_824, 2_147_483_648))
    monkeypatch.setattr(network, "_resource_module", lambda: mismatch)
    with pytest.raises(network.NetworkBoundaryError):
        network.establish_parser_address_space_limit()


def test_parser_worker_refuses_to_set_limit_after_parser_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeResource()
    monkeypatch.setattr(network, "_resource_module", lambda: fake)
    monkeypatch.setitem(sys.modules, "pyarrow", ModuleType("pyarrow"))
    with pytest.raises(network.NetworkBoundaryError) as raised:
        network.establish_parser_address_space_limit()
    assert raised.value.code is network.BoundaryErrorCode.PARSER_RESOURCE_LIMIT
    assert fake.calls == []
