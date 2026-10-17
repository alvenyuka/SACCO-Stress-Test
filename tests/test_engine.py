"""Checks that the engine is reproducible, behaves sensibly under stress, and that the committed
outputs/results.json (the source of every README figure) matches a fresh run."""
import json
import os

import pytest

import make_figures as mf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def fresh():
    return mf.build_results()


def test_same_seed_same_results(fresh):
    assert mf.build_results()["scenarios"] == fresh["scenarios"]


def test_losses_rise_with_severity(fresh):
    s = fresh["scenarios"]
    assert s["base"]["severity_score"] < s["adverse"]["severity_score"] < s["severe"]["severity_score"]
    assert s["base"]["total_ecl_kes"] < s["adverse"]["total_ecl_kes"] < s["severe"]["total_ecl_kes"]


def test_weighted_ecl_is_the_probability_weighted_sum(fresh):
    s = fresh["scenarios"]
    assert sum(v["probability_weight"] for v in s.values()) == pytest.approx(1.0)
    expected = sum(v["probability_weight"] * v["total_ecl_kes"] for v in s.values())
    assert fresh["probability_weighted"]["total_ecl_kes"] == pytest.approx(expected, rel=1e-9)


def test_capital_arithmetic(fresh):
    out = fresh["total_outstanding_kes"]
    for v in fresh["scenarios"].values():
        ratio = (mf.EQUITY_SHARE * out - v["total_ecl_kes"]) / out
        assert v["capital_ratio_after_losses"] == pytest.approx(ratio, abs=1e-9)
        expected_gap = max(0.0, mf.MIN_CAR * out - (mf.EQUITY_SHARE * out - v["total_ecl_kes"]))
        assert v["capital_shortfall_to_minimum_kes"] == pytest.approx(expected_gap, abs=0.01)
    assert fresh["scenarios"]["base"]["capital_shortfall_to_minimum_kes"] == 0
    assert fresh["scenarios"]["severe"]["capital_shortfall_to_minimum_kes"] > 0


def test_committed_results_match_a_fresh_run(fresh):
    with open(os.path.join(ROOT, "outputs", "results.json"), encoding="utf-8") as f:
        committed = json.load(f)
    assert committed == json.loads(json.dumps(fresh))
