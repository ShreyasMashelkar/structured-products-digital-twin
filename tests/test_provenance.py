"""Provenance tagging + the observed/interpolated/synthetic summary."""

import pytest

from spdt.core.provenance import Provenance
from spdt.core.types import SourceTag


def test_tag_lookup():
    prov = Provenance({"spot.NIFTY": SourceTag.OBSERVED})
    assert prov.tag("spot.NIFTY") is SourceTag.OBSERVED


def test_missing_tag_raises():
    with pytest.raises(KeyError):
        Provenance({}).tag("spot.NIFTY")


def test_summary_reports_fractions_per_bucket():
    prov = Provenance(
        {
            "a": SourceTag.OBSERVED,
            "b": SourceTag.OBSERVED,
            "c": SourceTag.OBSERVED,
            "d": SourceTag.INTERPOLATED,
        }
    )
    summary = prov.summary()
    assert summary[SourceTag.OBSERVED] == pytest.approx(0.75)
    assert summary[SourceTag.INTERPOLATED] == pytest.approx(0.25)
    assert sum(summary.values()) == pytest.approx(1.0)


def test_summary_of_empty_provenance_is_empty():
    assert Provenance({}).summary() == {}
