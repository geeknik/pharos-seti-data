"""Live HTTPS transport for the frozen Pharos v0.1.4 acquisition protocol.

Composes the frozen Section 10/18 network policy from ``control_network_v014``
into an executable client: IP-pinned TLS 1.3 connections with the registered
CA bundle, zero-follow redirects, bounded wire/decompressed spooling, the
deterministic three-attempt retry policy with 5/15-second waits, exact
transport-attempt evidence rows, the asynchronous TAP job protocol for Gaia
and SIMBAD, the synchronous VizieR request for Chen, and VOTable decoding
inside a fresh address-space-limited parser worker.

No function in this module consults ``status.toml``; authorization is enforced
by the CLI/workflow layer before any transport call. Every failure raises:
there is no silent truncation, fallback endpoint, or ambient-credential path.
"""

from __future__ import annotations

import hashlib
import re
import http.client
import multiprocessing
import socket
import ssl
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Final, Iterable, Literal, Mapping, Sequence

import pandas as pd

from pharos.control_evidence_v014 import TRANSPORT_COLUMNS
from pharos.control_network_v014 import (
    BODY_READ_TIMEOUT_SECONDS,
    BoundaryErrorCode,
    CA_BUNDLE_FILENAME,
    EndpointPolicy,
    FailureKind,
    GAIA_LOGICAL_DEADLINE_SECONDS,
    GAIA_POLL_INTERVAL_SECONDS,
    GAIA_POLL_OPERATIONS_MAX,
    NetworkBoundaryError,
    PEER_PORT,
    RESPONSE_HEADER_TIMEOUT_SECONDS,
    RetryDisposition,
    SIMBAD_LOGICAL_DEADLINE_SECONDS,
    TCP_CONNECT_TIMEOUT_SECONDS,
    TLS_HANDSHAKE_TIMEOUT_SECONDS,
    TRANSPORT_ATTEMPTS_MAX,
    TransportAttemptRecord,
    create_tls13_context,
    validate_async_job_url,
    validate_connected_peer,
    resolve_public_addresses,
    stream_response_to_spool,
    tls_server_hostname,
)
from pharos.control_network_v014 import (
    apply_best_effort_address_space_limit,
    classify_retry,
)

_SPOOL_DIRNAME: Final = "spool"
_TAP_PHASES_RUNNING: Final = frozenset({"PENDING", "QUEUED", "RUNNING", "EXECUTING"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection pinned to a validated public DNS answer.

    The socket is opened to the exact canonical IP returned by the immediately
    preceding policy-validated resolution, then wrapped with the registered
    TLS 1.3 context using the allow-listed hostname for SNI and certificate
    validation, per frozen Section 10.
    """

    def __init__(
        self,
        policy: EndpointPolicy,
        ca_bundle_path: Path,
        dns_answers: Sequence[str],
    ) -> None:
        super().__init__(
            policy.hostname,
            port=PEER_PORT,
            timeout=TCP_CONNECT_TIMEOUT_SECONDS,
        )
        self._policy = policy
        self._ca_bundle_path = ca_bundle_path
        self._dns_answers = dns_answers
        self.peer_ip: str | None = None
        self.leaf_certificate_der: bytes | None = None
        self.negotiated_tls_version: str | None = None

    def connect(self) -> None:  # noqa: D102 - http.client hook
        if not self._dns_answers:
            raise NetworkBoundaryError(BoundaryErrorCode.DNS_POLICY)
        pinned_ip = self._dns_answers[0]
        context = create_tls13_context(self._ca_bundle_path)
        sock = socket.create_connection(
            (pinned_ip, PEER_PORT), timeout=TLS_HANDSHAKE_TIMEOUT_SECONDS
        )
        try:
            self.sock = context.wrap_socket(
                sock, server_hostname=tls_server_hostname(self._policy.hostname)
            )
            tls_version = str(self.sock.version())
            der = self.sock.getpeercert(binary_form=True)
        except BaseException:
            sock.close()
            raise
        if der is None:
            raise NetworkBoundaryError(BoundaryErrorCode.TLS_POLICY)
        evidence = validate_connected_peer(
            expected_hostname=self._policy.hostname,
            peer_ip=pinned_ip,
            peer_port=PEER_PORT,
            validated_dns_answers=self._dns_answers,
            tls_version=tls_version,
            leaf_certificate_der=der,
        )
        self.peer_ip = evidence.peer_ip
        self.leaf_certificate_der = der


@dataclass(frozen=True, slots=True)
class _ExchangeResult:
    status: int
    headers: Mapping[str, str]
    spool_path: Path
    wire_bytes: int
    decompressed_bytes: int
    wire_sha256: str
    decompressed_sha256: str
    peer_ip: str
    leaf_certificate_sha256: str
    tls_version: str


class TransportJournal:
    """Accumulates exact transport-attempt evidence rows in global order."""

    def __init__(self, attempt_id: str) -> None:
        self._attempt_id = attempt_id
        self._records: list[TransportAttemptRecord] = []
        self._per_request_ordinals: dict[str, int] = {}

    @property
    def records(self) -> tuple[TransportAttemptRecord, ...]:
        return tuple(self._records)

    def _append(
        self,
        *,
        logical_request_id: str,
        phase: str,
        started: datetime,
        finished: datetime,
        outcome: str,
        status: int | None,
        hostname: str,
        peer_ip: str,
        leaf_certificate_sha256: str,
        exchange: _ExchangeResult | None,
        error_code: str | None,
    ) -> None:
        ordinal = self._per_request_ordinals.get(logical_request_id, 0) + 1
        self._per_request_ordinals[logical_request_id] = ordinal
        self._records.append(
            TransportAttemptRecord(
                attempt_id=self._attempt_id,
                logical_request_id=logical_request_id,
                transport_ordinal=ordinal,
                phase=phase,
                started_at=started,
                finished_at=finished,
                outcome=outcome,
                http_status=status,
                expected_hostname=hostname,
                peer_ip=peer_ip,
                peer_port=PEER_PORT,
                leaf_certificate_sha256=leaf_certificate_sha256,
                tls_version=exchange.tls_version if exchange else "TLSv1.3",
                redirect_count=0,
                wire_bytes=exchange.wire_bytes if exchange else 0,
                decompressed_bytes=exchange.decompressed_bytes if exchange else 0,
                wire_sha256=exchange.wire_sha256 if exchange else ("0" * 64),
                decompressed_sha256=exchange.decompressed_sha256 if exchange else ("0" * 64),
                error_code=error_code,
            )
        )

    def to_frame(self) -> pd.DataFrame:
        if not self._records:
            frame = pd.DataFrame(columns=list(TRANSPORT_COLUMNS))
            return frame
        frame = pd.DataFrame(
            [
                {
                    "attempt_id": record.attempt_id,
                    "logical_request_id": record.logical_request_id,
                    "transport_ordinal": record.transport_ordinal,
                    "phase": record.phase,
                    "started_at": record.started_at,
                    "finished_at": record.finished_at,
                    "outcome": record.outcome,
                    "http_status": record.http_status,
                    "expected_hostname": record.expected_hostname,
                    "peer_ip": record.peer_ip,
                    "peer_port": record.peer_port,
                    "leaf_certificate_sha256": record.leaf_certificate_sha256,
                    "tls_version": record.tls_version,
                    "redirect_count": record.redirect_count,
                    "wire_bytes": record.wire_bytes,
                    "decompressed_bytes": record.decompressed_bytes,
                    "wire_sha256": record.wire_sha256,
                    "decompressed_sha256": record.decompressed_sha256,
                    "error_code": record.error_code,
                }
                for record in self._records
            ]
        )
        if len(frame.columns) != len(TRANSPORT_COLUMNS) or tuple(frame.columns) != tuple(
            TRANSPORT_COLUMNS
        ):
            raise ValueError("transport evidence columns do not match the registered schema")
        return frame


def _phase_exchange(
    *,
    service: str,
    method: str,
    path: str,
    body: bytes | None,
    headers: Mapping[str, str],
    attempt_directory: Path,
    spool_filename: str,
    ca_bundle_path: Path,
    allow_location_status: bool,
) -> tuple[_ExchangeResult | None, int | None, str | None]:
    """Run one HTTP exchange; return (result, http_status, error_code).

    A ``None`` result with an ``error_code`` marks a pre-response or protocol
    failure for retry classification; a completed exchange is returned even
    when its status will be classified fatal (HTTP_STATUS path).
    """
    endpoint_policy = _policy_for(service)
    dns_answers = resolve_public_addresses(endpoint_policy.hostname)
    connection = _PinnedHTTPSConnection(endpoint_policy, ca_bundle_path, dns_answers)
    try:
        connection.connect()
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", f"{endpoint_policy.hostname}:{PEER_PORT}")
        for name, value in headers.items():
            connection.putheader(name, value)
        if body is not None:
            connection.putheader("Content-Length", str(len(body)))
        connection.putheader("Accept-Encoding", "gzip")
        connection.putheader("Connection", "close")
        connection.endheaders(message_body=body)
        connection.sock.settimeout(RESPONSE_HEADER_TIMEOUT_SECONDS)
        response = connection.getresponse()
        if connection.sock is not None:
            connection.sock.settimeout(BODY_READ_TIMEOUT_SECONDS)
        status = int(response.status)
        location = response.getheader("Location")
        if status in (301, 302, 303, 307, 308):
            if not allow_location_status:
                return None, status, "http_" + str(status)
            if location is None:
                return None, status, "redirect_without_location"
        if status >= 400:
            response.read()
            return None, status, "http_" + str(status)

        def chunks() -> Iterable[bytes]:
            while True:
                block = response.read1(65536)
                if not block:
                    break
                yield block

        encoding_header = (response.getheader("Content-Encoding") or "identity").strip().lower()
        if encoding_header not in ("identity", "gzip"):
            return None, status, "content_encoding_policy"
        spool = stream_response_to_spool(
            chunks(),
            attempt_directory=attempt_directory,
            filename=spool_filename,
            content_encoding=encoding_header,  # type: ignore[arg-type]
        )
        leaf = hashlib.sha256(connection.leaf_certificate_der or b"").hexdigest()
        result = _ExchangeResult(
            status=status,
            headers=dict(response.getheaders()),
            spool_path=spool.path,
            wire_bytes=spool.wire_bytes,
            decompressed_bytes=spool.decompressed_bytes,
            wire_sha256=spool.wire_sha256,
            decompressed_sha256=spool.decompressed_sha256,
            peer_ip=connection.peer_ip or "",
            leaf_certificate_sha256=leaf,
            tls_version=connection.negotiated_tls_version or "TLSv1.3",
        )
        return result, status, None
    except NetworkBoundaryError:
        raise
    except (socket.timeout, TimeoutError):
        return None, None, "timeout"
    except (ConnectionError, ssl.SSLEOFError, ssl.SSLZeroReturnError):
        return None, None, "tls_close_notify_loss"
    except AttributeError:
        return None, None, "connection_reset"
    except (ssl.SSLError, http.client.HTTPException, OSError):
        return None, None, "connection_reset"
    finally:
        try:
            connection.close()
        except BaseException:
            pass


def policy_host(service: str) -> str:
    return _policy_for(service).hostname


def policy_path(service: str) -> str:
    return _policy_for(service).path


def _policy_for(service: str) -> EndpointPolicy:
    from pharos.control_network_v014 import ENDPOINT_POLICIES

    if service not in ENDPOINT_POLICIES:
        raise NetworkBoundaryError(BoundaryErrorCode.ENDPOINT_POLICY)
    return ENDPOINT_POLICIES[service]


def _run_with_retries(
    *,
    journal: TransportJournal,
    logical_request_id: str,
    phase: str,
    service: str,
    attempt_directory: Path,
    spool_basename: str,
    ca_bundle_path: Path,
    exchange_callable: Callable[[str], tuple[_ExchangeResult | None, int | None, str | None]],
    allow_location_status: bool = False,
    method: str = "GET",
    path: str = "",
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> _ExchangeResult:
    """Execute one transport phase under the exact frozen retry policy."""
    hostname = policy_host(service)
    operation_attempt = 1
    while operation_attempt <= TRANSPORT_ATTEMPTS_MAX:
        spool_name = f"{spool_basename}.try{operation_attempt}"
        started = _utc_now()
        result, status, error_code = exchange_callable(spool_name)
        finished = _utc_now()
        received = result.wire_bytes if result else 0
        succeeded = result is not None and (
            200 <= result.status < 300
            or (
                allow_location_status
                and result.status in (301, 302, 303, 307, 308)
                and (result.headers.get("Location") or result.headers.get("location"))
            )
        )
        if succeeded:
            assert result is not None
            journal._append(
                logical_request_id=logical_request_id,
                phase=phase,
                started=started,
                finished=finished,
                outcome="success",
                status=status,
                hostname=hostname,
                peer_ip=result.peer_ip,
                leaf_certificate_sha256=result.leaf_certificate_sha256,
                exchange=result,
                error_code=None,
            )
            return result
        failure_kind = (
            FailureKind.HTTP_STATUS if result is not None else _failure_kind(error_code)
        )
        decision = classify_retry(
            failure_kind=failure_kind,
            operation_attempt=operation_attempt,
            response_bytes_received=received,
            http_status=status,
        )
        outcome = (
            "retryable_failure"
            if decision.disposition is RetryDisposition.RETRY
            else "fatal_failure"
        )
        journal._append(
            logical_request_id=logical_request_id,
            phase=phase,
            started=started,
            finished=finished,
            outcome=outcome,
            status=status,
            hostname=hostname,
            peer_ip=result.peer_ip if result else "0.0.0.0",
            leaf_certificate_sha256=(
                result.leaf_certificate_sha256 if result else "0" * 64
            ),
            exchange=result,
            error_code=None if succeeded else (error_code or decision.error_code),
        )
        if decision.disposition is not RetryDisposition.RETRY:
            import logging

            logging.getLogger(__name__).warning(
                "transport phase failed: request=%s phase=%s attempt=%d status=%s code=%s",
                logical_request_id,
                phase,
                operation_attempt,
                status,
                error_code or decision.error_code,
            )
            raise NetworkBoundaryError(BoundaryErrorCode.RETRY_POLICY)
        time.sleep(decision.wait_seconds or 0)
        operation_attempt += 1
    raise NetworkBoundaryError(BoundaryErrorCode.RETRY_POLICY)


def _failure_kind(error_code: str | None) -> FailureKind:
    if error_code == "timeout":
        return FailureKind.TIMEOUT
    if error_code == "connection_reset":
        return FailureKind.CONNECTION_RESET
    if error_code == "tls_close_notify_loss":
        return FailureKind.TLS_CLOSE_NOTIFY_LOSS
    if error_code and error_code.startswith("http_"):
        return FailureKind.HTTP_STATUS
    return FailureKind.OTHER


def fetch_sync(
    *,
    service: Literal["chen"],
    query_string: str,
    journal: TransportJournal,
    logical_request_id: str,
    attempt_directory: Path,
    ca_bundle_path: Path,
) -> Path:
    """Synchronous GET used for the single registered Chen catalog request."""
    if service != "chen":
        raise NetworkBoundaryError(BoundaryErrorCode.ENDPOINT_POLICY)
    path = policy_path(service) + "?" + query_string

    def exchange(spool_name: str) -> tuple[_ExchangeResult | None, int | None, str | None]:
        return _phase_exchange(
            service="chen",
            method="GET",
            path=path,
            body=None,
            headers={"User-Agent": "pharos-v0.1.4-control-population/1.0"},
            attempt_directory=attempt_directory,
            spool_filename=spool_name,
            ca_bundle_path=ca_bundle_path,
            allow_location_status=False,
        )

    result = _run_with_retries(
        journal=journal,
        logical_request_id=logical_request_id,
        phase="sync",
        service="chen",
        attempt_directory=attempt_directory,
        spool_basename=f"{logical_request_id}",
        ca_bundle_path=ca_bundle_path,
        exchange_callable=exchange,
    )
    return result.spool_path


def execute_tap_async(
    *,
    service: Literal["gaia", "simbad"],
    query_text: str,
    journal: TransportJournal,
    logical_request_id: str,
    attempt_directory: Path,
    ca_bundle_path: Path,
) -> Path:
    """Submit, poll, and fetch one asynchronous TAP job; return the result spool."""
    if service not in ("gaia", "simbad"):
        raise NetworkBoundaryError(BoundaryErrorCode.ENDPOINT_POLICY)
    deadline_seconds = (
        GAIA_LOGICAL_DEADLINE_SECONDS
        if service == "gaia"
        else SIMBAD_LOGICAL_DEADLINE_SECONDS
    )
    logical_deadline = time.monotonic() + deadline_seconds
    base_path = policy_path(service) + "/async"
    form = urllib.parse.urlencode(
        {
            "REQUEST": "doQuery",
            "LANG": "ADQL",
            "FORMAT": "votable",
            "PHASE": "RUN",
            "QUERY": query_text,
        }
    ).encode("ascii")
    submit_headers: dict[str, str] = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "pharos-v0.1.4-control-population/1.0",
    }

    def submit_exchange(spool_name: str) -> tuple[_ExchangeResult | None, int | None, str | None]:
        return _phase_exchange(
            service=service,
            method="POST",
            path=base_path,
            body=form,
            headers=submit_headers,
            attempt_directory=attempt_directory,
            spool_filename=spool_name,
            ca_bundle_path=ca_bundle_path,
            allow_location_status=True,
        )

    submit = _run_with_retries(
        journal=journal,
        logical_request_id=logical_request_id,
        phase="submit",
        service=service,
        attempt_directory=attempt_directory,
        spool_basename=f"{logical_request_id}.submit",
        ca_bundle_path=ca_bundle_path,
        exchange_callable=submit_exchange,
        allow_location_status=True,
    )
    location = submit.headers.get("Location") or submit.headers.get("location")
    if not location:
        raise ValueError("tap job submission returned no location header")
    job_url = validate_async_job_url(service, location)
    job_path = urllib.parse.urlsplit(job_url).path

    polls = 0
    while True:
        if time.monotonic() >= logical_deadline or polls >= GAIA_POLL_OPERATIONS_MAX:
            raise ValueError("logical request deadline exceeded")
        time.sleep(GAIA_POLL_INTERVAL_SECONDS)

        def poll_exchange(spool_name: str) -> tuple[_ExchangeResult | None, int | None, str | None]:
            return _phase_exchange(
                service=service,
                method="GET",
                path=job_path + "/phase",
                body=None,
                headers={"User-Agent": "pharos-v0.1.4-control-population/1.0"},
                attempt_directory=attempt_directory,
                spool_filename=spool_name,
                ca_bundle_path=ca_bundle_path,
                allow_location_status=False,
            )

        polls += 1
        poll = _run_with_retries(
            journal=journal,
            logical_request_id=logical_request_id,
            phase="poll",
            service=service,
            attempt_directory=attempt_directory,
            spool_basename=f"{logical_request_id}.poll{polls}",
            ca_bundle_path=ca_bundle_path,
            exchange_callable=poll_exchange,
        )
        phase_text = poll.spool_path.read_text(encoding="ascii").strip().upper()
        if phase_text == "COMPLETED":
            break
        if phase_text in ("ERROR", "ABORTED"):
            raise ValueError("tap job reached a terminal error phase")

    def jobdoc_exchange(spool_name: str) -> tuple[_ExchangeResult | None, int | None, str | None]:
        return _phase_exchange(
            service=service,
            method="GET",
            path=job_path,
            body=None,
            headers={"User-Agent": "pharos-v0.1.4-control-population/1.0"},
            attempt_directory=attempt_directory,
            spool_filename=spool_name,
            ca_bundle_path=ca_bundle_path,
            allow_location_status=False,
        )

    job_doc = _run_with_retries(
        journal=journal,
        logical_request_id=logical_request_id,
        phase="fetch",
        service=service,
        attempt_directory=attempt_directory,
        spool_basename=f"{logical_request_id}.jobdoc",
        ca_bundle_path=ca_bundle_path,
        exchange_callable=jobdoc_exchange,
    )
    match = re.search(rb'<uws:result[^>]*xlink:href="([^"]+)"', job_doc.spool_path.read_bytes())
    if match is None:
        raise ValueError("completed tap job exposes no result href")
    result_url = validate_async_job_url(service, match.group(1).decode("ascii"))
    result_path = urllib.parse.urlsplit(result_url).path

    def fetch_exchange(spool_name: str) -> tuple[_ExchangeResult | None, int | None, str | None]:
        return _phase_exchange(
            service=service,
            method="GET",
            path=result_path,
            body=None,
            headers={"User-Agent": "pharos-v0.1.4-control-population/1.0"},
            attempt_directory=attempt_directory,
            spool_filename=spool_name,
            ca_bundle_path=ca_bundle_path,
            allow_location_status=False,
        )

    result = _run_with_retries(
        journal=journal,
        logical_request_id=logical_request_id,
        phase="fetch",
        service=service,
        attempt_directory=attempt_directory,
        spool_basename=f"{logical_request_id}.result",
        ca_bundle_path=ca_bundle_path,
        exchange_callable=fetch_exchange,
    )
    return result.spool_path


def _decode_worker(
    spool_path: str,
    expected_columns: Sequence[tuple[str, str, bool]],
    connection_sender,
) -> None:
    """Parser worker: containment before any table library import/use."""
    try:
        apply_best_effort_address_space_limit()
        from astropy.io.votable import parse

        # verify="warn": astropy unit-string pedantry (e.g. log(cm.s**-2)) must
        # not reject an otherwise well-formed table; structural strictness is
        # enforced below by the exact column/type contract and downstream gates.
        table = parse(spool_path, verify="warn").get_first_table().to_table(
            use_names_over_ids=True
        )
        frame = table.to_pandas()
        if tuple(frame.columns) != tuple(name for name, _, _ in expected_columns):
            raise ValueError(
                f"decoded columns {tuple(frame.columns)} do not match registered query output"
            )
        for name, logical, nullable in expected_columns:
            series = frame[name]
            if logical == "float64":
                frame[name] = pd.to_numeric(series, errors="raise").astype("float64")
            elif logical == "int64":
                numeric = pd.to_numeric(series, errors="raise")
                if numeric.isna().any():
                    if not nullable:
                        raise ValueError(f"{name} has nulls but is registered non-null")
                    frame[name] = numeric.astype("Int64").astype("int64")
                else:
                    frame[name] = numeric.astype("int64")
            elif logical == "bool":
                frame[name] = series.astype(bool)
            elif logical == "string":
                frame[name] = series.astype("string")
        # Nullable floats keep NaN as the registered null marker; the
        # normalizer validates float64 dtypes with NaN-nullable domains.
        connection_sender.send(("ok", frame))
    except BaseException as exc:  # worker reports failures through the pipe only
        connection_sender.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        connection_sender.close()


def decode_votable_table(
    spool_path: Path, expected_columns: Sequence[tuple[str, str, bool]]
) -> pd.DataFrame:
    """Decode a spooled VOTable in a fresh limited worker; exact typed columns."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_decode_worker,
        args=(str(spool_path), tuple(expected_columns), sender),
        daemon=False,
    )
    process.start()
    sender.close()
    try:
        status, payload = receiver.recv()
    finally:
        receiver.close()
        process.join(timeout=60)
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
            raise NetworkBoundaryError(BoundaryErrorCode.PARSER_RESOURCE_LIMIT)
    if process.exitcode not in (0, None):
        raise NetworkBoundaryError(BoundaryErrorCode.PARSER_RESOURCE_LIMIT)
    if status != "ok":
        raise ValueError(f"votable decode rejected: {payload}")
    return payload


def registered_ca_bundle_path(repository_root: Path) -> Path:
    """Locate the packaged CA bundle by its registered content-addressed name."""
    candidate = repository_root / "controls" / CA_BUNDLE_FILENAME
    if not candidate.is_file():
        raise NetworkBoundaryError(BoundaryErrorCode.CA_BUNDLE_POLICY)
    return candidate
