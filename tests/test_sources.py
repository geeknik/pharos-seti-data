"""Unit tests for ADQL construction.

These exercise the pure helpers in ``pharos.sources`` and do not contact
the Gaia archive.
"""

from __future__ import annotations

import hashlib

import pytest

from pharos import sources


class TestBuildTargetADQL:
    def test_single_source_id_inlined(self) -> None:
        query = sources.build_target_adql([2644370304260053376])
        assert "2644370304260053376" in query
        assert "IN (2644370304260053376)" in query

    def test_multiple_source_ids_inlined(self) -> None:
        ids = [
            3496509309189181184,
            4843191593270342656,
            2644370304260053376,
        ]
        query = sources.build_target_adql(ids)
        for sid in ids:
            assert str(sid) in query

    def test_empty_iterable_raises(self) -> None:
        with pytest.raises(ValueError):
            sources.build_target_adql([])

    def test_non_int_source_id_rejected(self) -> None:
        with pytest.raises(TypeError):
            sources.build_target_adql(["12345"])  # type: ignore[list-item]

    def test_bool_rejected_as_int_alias(self) -> None:
        # bools are ints in Python; reject them as source IDs to avoid
        # silently formatting `True` as `1` in ADQL.
        with pytest.raises(TypeError):
            sources.build_target_adql([True])  # type: ignore[list-item]

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            sources.build_target_adql([-1])

    def test_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            sources.build_target_adql([0])

    def test_oversized_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            sources.build_target_adql([1 << 65])


class TestBuildQuietNegativeSplitQueries:
    """The split-query path that's actually submitted to the Gaia archive."""

    def test_gaia_step_includes_gaia_source(self) -> None:
        query = sources.build_quiet_negative_gaia_adql(limit=1000)
        assert sources.GAIA_SOURCE_TABLE in query
        assert sources.ALLWISE_XMATCH_TABLE not in query
        assert sources.TMASS_XMATCH_TABLE not in query

    def test_gaia_step_includes_pre_registered_cuts(self) -> None:
        query = sources.build_quiet_negative_gaia_adql(limit=1000)
        cov = sources.COVERAGE_CLASS_CUTS
        qn = sources.QUIET_NEGATIVE_CUTS
        assert f"parallax_over_error >= {cov['parallax_over_error_min']}" in query
        assert f"phot_g_mean_mag <= {cov['g_mag_max']}" in query
        assert f"ruwe < {qn['ruwe_max']}" in query
        assert f"ABS(b) > {qn['galactic_latitude_min_deg']}" in query

    def test_gaia_step_uses_indexed_distance_predicate(self) -> None:
        # The computed-distance form (`1000.0 / parallax`) is dramatically
        # slower server-side than the equivalent indexed parallax-bound.
        query = sources.build_quiet_negative_gaia_adql(limit=1000)
        assert "1000.0 / parallax" not in query
        assert "parallax >= 5.000000" in query

    def test_allwise_step_filters_by_ids(self) -> None:
        ids = [3496509309189181184, 4843191593270342656]
        query = sources.build_allwise_for_ids_adql(ids)
        for sid in ids:
            assert str(sid) in query
        assert sources.ALLWISE_XMATCH_TABLE in query
        assert sources.ALLWISE_PHOTO_TABLE in query

    def test_tmass_step_filters_by_ids(self) -> None:
        ids = [3496509309189181184]
        query = sources.build_tmass_for_ids_adql(ids)
        assert "3496509309189181184" in query
        assert sources.TMASS_XMATCH_TABLE in query
        assert sources.TMASS_PHOTO_TABLE in query

    def test_allwise_step_validates_ids(self) -> None:
        with pytest.raises(ValueError):
            sources.build_allwise_for_ids_adql([])
        with pytest.raises(TypeError):
            sources.build_allwise_for_ids_adql(["12345"])  # type: ignore[list-item]

    def test_gaia_step_limit_is_inlined(self) -> None:
        query = sources.build_quiet_negative_gaia_adql(limit=2500)
        assert "TOP 2500" in query

    def test_gaia_step_unlimited_omits_top(self) -> None:
        query = sources.build_quiet_negative_gaia_adql(limit=None)
        assert "TOP" not in query

    def test_gaia_step_hash_is_stable(self) -> None:
        q1 = sources.build_quiet_negative_gaia_adql(limit=1000)
        q2 = sources.build_quiet_negative_gaia_adql(limit=1000)
        assert q1 == q2
        assert hashlib.sha256(q1.encode("utf-8")).hexdigest() == hashlib.sha256(
            q2.encode("utf-8")
        ).hexdigest()
