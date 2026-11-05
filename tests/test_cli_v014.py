from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from pharos import cli
from pharos import control_loaders_v014 as loaders
from pharos import control_workflow_v014 as workflow


def test_parser_exposes_separate_v014_roles_and_quarantines_v012() -> None:
    parser = cli.build_parser()
    assert parser.parse_args(["v014_control_preflight"]).func is cli.cmd_v014_control_preflight
    assert parser.parse_args(["v014_control_acquire"]).func is cli.cmd_v014_control_acquire
    assert (
        parser.parse_args(["v014_review_candidate", "--candidate-dir", "controls/x"]).func
        is cli.cmd_v014_review_candidate
    )
    assert (
        parser.parse_args(["v014_load_registered_raw", "--entry-id", "raw"]).func
        is cli.cmd_v014_load_registered_raw
    )
    assert (
        parser.parse_args(["v014_load_registered_final", "--entry-id", "release"]).func
        is cli.cmd_v014_load_registered_final
    )
    assert (
        parser.parse_args(["reproduce_failed_v012_pilot"]).func
        is cli.cmd_reproduce_failed_v012_pilot
    )
    with pytest.raises(SystemExit):
        parser.parse_args(["fetch_quiet_negative", "--output", "controls/unsafe.parquet"])


def test_v014_preflight_passes_with_pinned_reviewer_trust_root(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "verify_frozen_registration", lambda: None)
    monkeypatch.setattr(
        workflow, "reject_ambient_network_environment", lambda environ=None: None
    )
    monkeypatch.setattr(workflow, "producer_identity", lambda: object())
    monkeypatch.setattr(workflow, "probe_rename_excl", lambda parent: None)
    result = cli.cmd_v014_control_preflight(argparse.Namespace(publication_parent="controls"))
    output = capsys.readouterr().out
    assert result == 0
    assert "status: passed" in output
    assert "reviewer_trust_root" not in output


def test_v014_acquisition_role_refuses_without_operator_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Path] = []

    def passed(*, publication_parent: Path) -> None:
        calls.append(publication_parent)

    monkeypatch.setattr(workflow, "require_acquisition_preflight", passed)
    result = cli.cmd_v014_control_acquire(argparse.Namespace(publication_parent="controls"))
    assert result == 2
    # The repository status boundary refuses acquisition before any local
    # gate or network path can run.
    assert calls == []


def test_v014_candidate_review_uses_review_only_loader(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = loaders.LoadedCandidate(Path("controls"), {}, "1" * 64, False, None)
    monkeypatch.setattr(loaders, "load_candidate_for_review", lambda _path: expected)
    result = cli.cmd_v014_review_candidate(argparse.Namespace(candidate_dir="controls"))
    assert result == 0
    assert "status: review_only" in capsys.readouterr().out


def test_v014_registered_loaders_fail_closed_with_empty_registry() -> None:
    raw = cli.cmd_v014_load_registered_raw(argparse.Namespace(entry_id="missing"))
    final = cli.cmd_v014_load_registered_final(argparse.Namespace(entry_id="missing"))
    assert raw == 2
    assert final == 2


def test_v014_candidate_review_rejects_path_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def forbidden(_path: Path) -> loaders.LoadedCandidate:
        nonlocal called
        called = True
        raise AssertionError("loader must not receive an escaped path")

    monkeypatch.setattr(loaders, "load_candidate_for_review", forbidden)
    result = cli.cmd_v014_review_candidate(argparse.Namespace(candidate_dir="../escape"))
    assert result == 2
    assert not called
