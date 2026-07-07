"""Outcome Lab: reproducible issuance and implementable hedge comparisons."""

from spdt.outcomes import OutcomeTerms, hedge_comparison, issuance_study

TERMS = OutcomeTerms(2.0, 4, 0.02, 0.70)


def test_issuance_study_reports_a_distribution_and_tail():
    result = issuance_study(24_000.0, 0.20, TERMS)
    assert result["n_issuances"] > 100
    assert 0.0 <= result["autocall_rate_pct"] <= 100.0
    assert 0.0 <= result["loss_rate_pct"] <= 100.0
    assert result["tail_return_pct"] <= result["mean_return_pa_pct"]
    assert len(result["cohorts"]) < result["n_issuances"]  # display path vs pooled ensemble
    assert result["robustness"]["n_paths"] == 5
    assert "Synthetic" in result["source"]  # do not mislabel generated data as observed history


def test_semistatic_hedge_reduces_out_of_sample_pnl_risk():
    result = hedge_comparison(24_000.0, 0.20, 0.05, 0.01, TERMS)
    rows = {row["strategy"]: row for row in result["strategies"]}
    assert rows["Semi-static"]["pnl_std"] < rows["Unhedged"]["pnl_std"]
    assert rows["Unhedged"]["expected_shortfall_95"] > 0.0
    assert rows["Delta-only"]["transaction_cost"] > 0.0
    assert rows["Semi-static"]["transaction_cost"] > 0.0
    assert rows["Hybrid"]["transaction_cost"] > rows["Delta-only"]["transaction_cost"]
    assert rows["Semi-static"]["turnover"] > rows["Delta-only"]["turnover"]
    assert rows["Semi-static"]["turnover"] <= 5 * TERMS.notional
    assert rows[result["best_strategy"]]["eligible"] is True
    assert result["selection_rule"]
    assert result["static_instruments"] >= 7
