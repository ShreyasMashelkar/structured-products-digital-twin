"""Tests for Management Reporting Engine (Phase 10)."""
from src.reporting.management_report import ManagementReportGenerator
import datetime

def test_generate_daily_summary():
    xva = {'Total_CVA': 100.0, 'Total_DVA': 20.0, 'Total_FVA': 10.0}
    limit = {'Total_Breaches': 1, 'Total_Warnings': 2}
    raroc = {'Portfolio_RAROC': 0.15, 'Portfolio_EVA': 50000.0}
    econ = {'Economic_Capital': 250000.0}
    wwr = {'WWR_Impact': 30.0, 'Stressed_CVA': 130.0, 'Effective_Multiplier': 1.3}
    attr = {'Total_Change': 5.0}
    
    rep_gen = ManagementReportGenerator(xva, limit, raroc, econ, wwr, attr)
    res = rep_gen.generate_daily_summary()
    
    assert res['Report_Date'] == datetime.date.today().isoformat()
    assert res['Executive_Summary']['Total_XVA'] == 100.0 - 20.0 + 10.0
    assert res['Executive_Summary']['CVA_DoD_Change'] == 5.0
    
    assert res['Capital_And_Returns']['Portfolio_RAROC_Pct'] == 15.0
    assert res['Capital_And_Returns']['Economic_Capital'] == 250000.0
    
    assert res['Stress_And_WWR']['Stressed_CVA'] == 130.0
    assert res['Stress_And_WWR']['WWR_Impact'] == 30.0
    
    assert res['Governance']['Active_Limit_Breaches'] == 1
    assert res['Governance']['Status'] == 'RED'

def test_governance_status():
    rep_gen_amber = ManagementReportGenerator({}, {'Total_Breaches': 0, 'Total_Warnings': 1}, {}, {}, {}, {})
    assert rep_gen_amber.generate_daily_summary()['Governance']['Status'] == 'AMBER'
    
    rep_gen_green = ManagementReportGenerator({}, {'Total_Breaches': 0, 'Total_Warnings': 0}, {}, {}, {}, {})
    assert rep_gen_green.generate_daily_summary()['Governance']['Status'] == 'GREEN'
