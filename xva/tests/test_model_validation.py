import pytest
import pandas as pd
from src.validation.model_validator import ModelValidationSuite


@pytest.fixture(scope='module')
def suite():
    return ModelValidationSuite()


def test_run_all_returns_dataframe(suite):
    df = suite.run_all()
    assert isinstance(df, pd.DataFrame)
    assert 'Status' in df.columns
    assert len(df) >= 6


def test_bootstrap_consistency(suite):
    result = suite.test_bootstrap_consistency()
    assert result['max_error_bps'] < 25.0, "Bootstrap RMSE > 25bps"


def test_positive_forwards(suite):
    result = suite.test_positive_forwards()
    assert result['n_negative'] == 0, "Negative forward rates detected"


def test_mc_convergence_runs(suite):
    result = suite.test_mc_convergence(n_paths_list=[500, 1000, 2000])
    assert 'ee_estimates' in result
    assert len(result['ee_estimates']) == 3
