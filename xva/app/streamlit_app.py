"""
INR OTC Derivatives Risk & XVA Analytics Platform
Bloomberg Terminal-style dark UI — multi-page Streamlit dashboard
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import io
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# Project imports
from src.data_ingestion.market_data import (
    get_ois_market_data, get_gsec_market_data, get_counterparty_data,
    get_sample_portfolio, get_csa_scenarios, get_stress_scenarios,
    get_policy_rates, get_data_provenance, OIS_TENOR_LABELS
)
from src.curves.ois_curve import OISCurve, GSecCurve
from src.pricing.swap_pricer import SwapPricer, price_portfolio
from src.montecarlo.hull_white import HullWhite1F, run_exposure_simulation
from src.csa.collateral import CSAEngine, compare_csa_scenarios
from src.xva.cva import CVAEngine, CreditCurve
from src.xva.fva import FVAEngine
from src.xva.kva import KVAEngine
from src.sa_ccr.regulatory import SACCRCalculator, compute_rwa, compute_capital_requirement
from src.stress.stress_testing import stress_test_swap, run_full_stress_test

# V2 Imports
from src.data_ingestion.portfolio_manager import PortfolioManager
from src.portfolio.netting_engine import NettingEngine
from src.portfolio.capital_optimizer import CapitalOptimizer



# Page Configuration
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="INR XVA Analytics Platform",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────────────────────
# Bloomberg Theme CSS — loaded from file
# ─────────────────────────────────────────────────────────────
_css_path = os.path.join(os.path.dirname(__file__), "styles", "bloomberg_theme.css")
with open(_css_path) as _f:
    st.markdown(f"<style>{_f.read()}</style>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# Bloomberg Plotly theme
# ─────────────────────────────────────────────────────────────
_MONO = 'JetBrains Mono, Courier New, monospace'

PLOTLY_LAYOUT = dict(
    template='plotly_dark',
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='#0d1117',
    font=dict(family=_MONO, color='#e0e0e0', size=10),
    title_font=dict(family=_MONO, size=11, color='#ff6600'),
    legend=dict(
        bgcolor='#101418',
        bordercolor='#243040',
        borderwidth=1,
        font=dict(family=_MONO, size=9, color='#e0e0e0')
    ),
    margin=dict(l=44, r=16, t=34, b=32),
    xaxis=dict(
        gridcolor='#1a2230',
        zerolinecolor='#243040',
        showline=True,
        linecolor='#243040',
        linewidth=1,
        mirror=False,
        tickfont=dict(family=_MONO, color='#8899aa', size=9),
        title_font=dict(family=_MONO, color='#8899aa', size=9),
    ),
    yaxis=dict(
        gridcolor='#1a2230',
        zerolinecolor='#243040',
        showline=True,
        linecolor='#243040',
        linewidth=1,
        mirror=False,
        tickfont=dict(family=_MONO, color='#8899aa', size=9),
        title_font=dict(family=_MONO, color='#8899aa', size=9),
    ),
    hoverlabel=dict(
        bgcolor='#141a20',
        bordercolor='#ff6600',
        font=dict(family=_MONO, color='#e0e0e0', size=10),
    ),
)

COLORS = {
    'EE':        '#00aaff',   # Electric blue — EE profile
    'EPE':       '#ffaa00',   # Amber         — EPE
    'PFE':       '#ff4444',   # Bright red    — PFE
    'ENE':       '#00cc66',   # Green         — ENE
    'primary':   '#00aaff',
    'secondary': '#8899aa',
    'accent':    '#ff6600',
    'success':   '#00cc66',
    'warning':   '#ffaa00',
    'danger':    '#cc2200',
    'danger_bright': '#ff3311',
    'info':      '#e0e0e0',
    'dim':       '#556677',
}

# Range selector buttons for time-series charts
_RANGE_BUTTONS = [
    dict(count=7,  label="1W", step="day",   stepmode="backward"),
    dict(count=1,  label="1M", step="month", stepmode="backward"),
    dict(count=3,  label="3M", step="month", stepmode="backward"),
    dict(count=6,  label="6M", step="month", stepmode="backward"),
    dict(count=1,  label="1Y", step="year",  stepmode="backward"),
    dict(step="all", label="ALL"),
]
_RANGESELECTOR = dict(
    buttons=_RANGE_BUTTONS,
    bgcolor='#101418',
    activecolor='#ff6600',
    bordercolor='#243040',
    borderwidth=1,
    font=dict(family=_MONO, color='#e0e0e0', size=9),
)

# ─────────────────────────────────────────────────────────────
# Bloomberg KPI tile helper + st.metric monkey-patch
# ─────────────────────────────────────────────────────────────
from datetime import datetime
import streamlit.delta_generator

def bbg_metric(*args, **kwargs):
    if len(args) > 0 and hasattr(args[0], 'markdown'):
        self = args[0];  args = args[1:]
    else:
        self = st

    label = args[0] if len(args) > 0 else kwargs.get("label", "")
    value = args[1] if len(args) > 1 else kwargs.get("value", "")
    delta = args[2] if len(args) > 2 else kwargs.get("delta", None)
    accent = kwargs.get("accent", "amber")   # amber | blue | green | red

    # Capture the metric for the active page's data export (best-effort).
    try:
        _EXPORT['metrics'].append(
            {'metric': str(label), 'value': str(value),
             'delta': '' if delta is None else str(delta)})
    except Exception:
        pass

    top_colors = {"amber": "#ff6600", "blue": "#00aaff", "green": "#00cc66", "red": "#cc2200"}
    top_color  = top_colors.get(accent, "#ff6600")

    delta_html = ""
    if delta is not None and str(delta).strip():
        s = str(delta).strip()
        if s.startswith("+") or (s.replace(".", "").replace(",", "").lstrip("+").lstrip("-").isdigit() and not s.startswith("-")):
            dc = "#00cc66"
        elif s.startswith("-"):
            dc = "#ff3311"
        else:
            dc = "#8899aa"
        delta_html = f"<div class='kpi-delta' style='color:{dc}'>{s}</div>"

    val_str = str(value)
    # right-align and color numbers by sign
    if val_str.lstrip("₹ ").lstrip("+").lstrip("-").replace(".","").replace(",","").isdigit():
        vc = "#00cc66" if not val_str.lstrip("₹ ").startswith("-") else "#ff3311"
    else:
        vc = "#e0e0e0"

    html = f"""<div class="kpi-tile" style="border-top:2px solid {top_color}">
  <div class="kpi-label">{label}</div>
  <div class="kpi-value" style="color:{vc}">{value}</div>
  {delta_html}
</div>"""
    self.markdown(html, unsafe_allow_html=True)

import streamlit as st
st.metric = bbg_metric
streamlit.delta_generator.DeltaGenerator.metric = bbg_metric

# ─────────────────────────────────────────────────────────────
# Top header bar (with live JS clock)
# ─────────────────────────────────────────────────────────────
_now = datetime.now()
header_html = f"""
<div class="bbg-header">
  <div class="bbg-logo">BBG</div>
  <div class="bbg-divider"></div>
  <div class="bbg-platform">INR OTC DERIVATIVES &nbsp;|&nbsp; RISK &amp; XVA ANALYTICS</div>
  <div class="bbg-spacer"></div>
  <div class="bbg-status"><div class="bbg-status-dot"></div>LIVE</div>
  <div class="bbg-divider"></div>
  <div class="bbg-date">{_now.strftime('%d %b %Y')}</div>
  <div class="bbg-divider"></div>
  <div class="bbg-clock" id="bbg-clock">{_now.strftime('%H:%M:%S IST')}</div>
</div>
<script>
  (function() {{
    function tick() {{
      var el = document.getElementById('bbg-clock');
      if (el) {{
        var d = new Date();
        var h = String(d.getHours()).padStart(2,'0');
        var m = String(d.getMinutes()).padStart(2,'0');
        var s = String(d.getSeconds()).padStart(2,'0');
        el.textContent = h + ':' + m + ':' + s + ' IST';
      }}
    }}
    setInterval(tick, 1000);
  }})();
</script>
"""
st.markdown(header_html, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# Sticky footer
# ─────────────────────────────────────────────────────────────
footer_html = f"""
<div class="bbg-footer">
  <div><span class="conn-ok">&#9679; CONNECTED</span> &nbsp;|&nbsp; NODE: XVA-ALPHA-01 &nbsp;|&nbsp; MKTDATA: RBI/CCIL/NSE</div>
  <div>EOD SNAP: {_now.strftime('%H:%M:%S IST')} &nbsp;|&nbsp; &copy; 2026 XVA ANALYTICS PLATFORM</div>
</div>
"""
st.markdown(footer_html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# Cached data loading and computation
# ─────────────────────────────────────────────────────────────
@st.cache_data
def run_v2_engines():
    """Run the V2 engines to compute portfolio metrics."""
    from src.curves.multi_curve import MultiCurveFramework
    mcf = MultiCurveFramework.build_from_market_data()
    ois_curve = mcf.discount
    cptys_df = PortfolioManager.load_counterparties()
    portfolio_df = PortfolioManager.load_portfolio()
    trades = portfolio_df.to_dict('records')
    
    hw_model = HullWhite1F(ois_curve, a=0.10, sigma=0.01)
    time_grid, rate_paths = hw_model.simulate_rates(n_paths=1200, n_steps=48, horizon=10.0)
    
    netting = NettingEngine(time_grid, rate_paths, hw_model)
    trade_mtm_paths = netting.calculate_trade_mtm_paths(trades, projection_curve=mcf.mibor)
    
    current_mtms = {tid: paths[:, 0].mean() for tid, paths in trade_mtm_paths.items()}
    csa_mtm = netting.aggregate_by_csa(trades, trade_paths=trade_mtm_paths)
    csa_exposures = netting.apply_collateral(csa_mtm)
    portfolio_exposure = netting.aggregate_portfolio(csa_exposures)
    
    cap_opt = CapitalOptimizer(ois_curve, cptys_df)
    ranked_df = cap_opt.rank_portfolio(trades, current_mtms)
    
    return {
        'ois_curve': ois_curve, 'cptys_df': cptys_df, 'portfolio_df': portfolio_df,
        'trades': trades, 'time_grid': time_grid, 'current_mtms': current_mtms,
        'csa_exposures': csa_exposures, 'portfolio_exposure': portfolio_exposure,
        'ranked_df': ranked_df, 'mcf': mcf
    }

@st.cache_data
def load_market_data():
    """Load all market data."""
    ois_data = get_ois_market_data()
    gsec_data = get_gsec_market_data()
    counterparties = get_counterparty_data()
    portfolio = get_sample_portfolio()
    policy_rates = get_policy_rates()
    return ois_data, gsec_data, counterparties, portfolio, policy_rates


@st.cache_data
def build_curves():
    """Build OIS and G-Sec curves."""
    ois_data = get_ois_market_data()
    gsec_data = get_gsec_market_data()

    ois_curve = OISCurve(
        tenors=ois_data['tenor_years'].values,
        rates=ois_data['ois_rate'].values
    )
    gsec_curve = GSecCurve(
        tenors=gsec_data['tenor_years'].values,
        yields=gsec_data['yield_rate'].values
    )
    return ois_curve, gsec_curve


@st.cache_data
def run_simulation(_curve, notional, fixed_rate, maturity, direction,
                   n_paths, a, sigma):
    """Run Monte Carlo simulation (cached)."""
    return run_exposure_simulation(
        _curve, notional=notional, fixed_rate=fixed_rate,
        maturity=maturity, direction=direction,
        n_paths=n_paths, a=a, sigma=sigma
    )


# Equity market-data fetches hit NSE over the network (8–18s blocking with the
# calibrated fallback). Cache them for the session so widget interactions on the
# equity pages don't re-fetch on every rerun.
@st.cache_data(ttl=300, show_spinner="Fetching NSE equity data…")
def cached_equity_market_data(index):
    from src.data_ingestion.equity_data import get_equity_market_data
    return get_equity_market_data(index)


@st.cache_data(ttl=300, show_spinner=False)
def cached_nifty_option_chain(index, spot, atm_vol):
    from src.data_ingestion.equity_data import get_nifty_option_chain
    return get_nifty_option_chain(index, spot=spot, atm_vol=atm_vol)


# FIMMDA bond fetch loops up to 5 business days at a 12s timeout each (up to
# ~60s when fimmda.org is unreachable). Cache so it blocks at most once.
@st.cache_data(ttl=600, show_spinner=False)
def cached_fimmda_zspread():
    from src.data_ingestion.market_data import _fetch_fimmda_bond_zspread
    return _fetch_fimmda_bond_zspread()


# ─────────────────────────────────────────────────────────────
# Sidebar Navigation — Bloomberg style
# ─────────────────────────────────────────────────────────────
PAGES = {
    "OVERVIEW": {
        "fkey": "F1",
        "pages": ["Executive Risk Dashboard"]
    },
    "TRADING BOOK": {
        "fkey": "F2",
        "pages": ["Trade Capture & Lifecycle", "Pre-Trade XVA Impact", "Trade Analytics"]
    },
    "COUNTERPARTY RISK": {
        "fkey": "F3",
        "pages": ["Counterparty Exposure Analytics", "Credit Risk Analytics",
                  "CVA Greeks & Hedging", "Portfolio WWR (Copula)",
                  "Collateral & Margin Analytics", "SIMM Initial Margin",
                  "CSA CTD Optionality", "Bilateral Valuation Analytics",
                  "Counterparty Limit Monitor", "XVA Explain & Attribution"]
    },
    "MARKET & QUANT": {
        "fkey": "F4",
        "pages": ["Rates & Volatility Analytics", "Volatility & Optionality Analytics",
                  "HW2F Term Structure", "PnL Explain"]
    },
    "CAPITAL & REG": {
        "fkey": "F5",
        "pages": ["Regulatory Capital Analytics", "FRTB-CVA Capital", "BA-CVA Capital",
                  "Capital & RAROC Analytics"]
    },
    "STRESS": {
        "fkey": "F6",
        "pages": ["Stress & Scenario Analysis"]
    },
    "MODEL RISK": {
        "fkey": "F7",
        "pages": ["Model Risk & Validation", "Exposure Backtesting"]
    },
    "INFRASTRUCTURE": {
        "fkey": "F8",
        "pages": ["Data & Infrastructure Monitor"]
    },
    "ADVANCED QUANT": {
        "fkey": "F9",
        "pages": ["AAD Greeks Engine", "Quasi-Monte Carlo", "Bermudan Exposure (LSM)",
                  "Cross-Currency XVA", "Stochastic WWR", "IFRS-13 Accounting"]
    },
    "EQUITY & HYBRID": {
        "fkey": "F10",
        "pages": ["Equity Derivatives", "Hybrid Cross-Asset XVA"]
    },
}

# Page → short label map for nav display
_PAGE_LABELS = {
    "Executive Risk Dashboard":      "EXEC RISK DASHBOARD",
    "Trade Capture & Lifecycle":     "TRADE CAPTURE",
    "Pre-Trade XVA Impact":          "PRE-TRADE XVA",
    "Trade Analytics":               "TRADE ANALYTICS",
    "Counterparty Exposure Analytics": "EXPOSURE ANALYTICS",
    "Credit Risk Analytics":         "CREDIT ANALYTICS",
    "CVA Greeks & Hedging":          "CVA GREEKS / HEDGE",
    "Portfolio WWR (Copula)":        "PORTFOLIO WWR",
    "Collateral & Margin Analytics": "COLLATERAL & MVA",
    "SIMM Initial Margin":           "SIMM IM / DIM",
    "CSA CTD Optionality":           "CSA CTD OPTION",
    "Bilateral Valuation Analytics": "BILATERAL CVA/DVA",
    "Counterparty Limit Monitor":    "LIMIT MONITOR",
    "XVA Explain & Attribution":     "XVA ATTRIBUTION",
    "Rates & Volatility Analytics":  "RATES & VOL",
    "Volatility & Optionality Analytics": "SWAPTION PRICER",
    "HW2F Term Structure":           "HW2F TERM STRUCT",
    "PnL Explain":                   "PNL EXPLAIN",
    "Regulatory Capital Analytics":  "SA-CCR / RWA",
    "FRTB-CVA Capital":              "FRTB-CVA SA",
    "BA-CVA Capital":                "BA-CVA BASIC",
    "Capital & RAROC Analytics":     "CAPITAL / RAROC",
    "Exposure Backtesting":          "EXPOSURE BACKTEST",
    "AAD Greeks Engine":             "AAD GREEKS",
    "Quasi-Monte Carlo":             "QUASI-MC (SOBOL)",
    "Bermudan Exposure (LSM)":       "BERMUDAN / LSM",
    "Cross-Currency XVA":            "CROSS-CCY XVA",
    "Stochastic WWR":                "STOCHASTIC WWR",
    "IFRS-13 Accounting":            "IFRS-13 XVA",
    "Equity Derivatives":            "EQUITY (NIFTY)",
    "Hybrid Cross-Asset XVA":        "HYBRID XVA",
    "Stress & Scenario Analysis":    "STRESS TESTING",
    "Model Risk & Validation":       "MODEL VALIDATION",
    "Data & Infrastructure Monitor": "INFRA MONITOR",
}

# ── Deploy build stamp — BUMP THIS STRING ON EVERY PUSH ──────────────
# If the sidebar/footer doesn't show this exact value on the cloud, the
# deployment is NOT serving your latest commit (stuck build / wrong branch).
BUILD_ID = "2026-06-08 · 3"

with st.sidebar:
    st.markdown("""
<div class="sidebar-header">
  <div class="platform-name">XVA TERMINAL</div>
  <div class="platform-sub">INR OTC DERIVATIVES &nbsp;&#9679;&nbsp; RISK ANALYTICS</div>
</div>
""", unsafe_allow_html=True)

    # Build stamp — bump BUILD_ID on every deploy to verify the LIVE version.
    st.markdown(f"""<div style='background:#1a0f00;border:1px solid #ff6600;
        border-radius:4px;text-align:center;color:#ff8a33;font-size:0.62rem;
        font-weight:700;letter-spacing:.10em;padding:4px;margin:2px 0 8px'>
        &#11042; BUILD {BUILD_ID}</div>""", unsafe_allow_html=True)

    # ── Data-source badge — honestly shows which tier (LIVE / CACHED /
    # SYNTHETIC) served each dataset this session. Loading the (cached)
    # market data first guarantees provenance is populated.
    load_market_data()
    _prov = get_data_provenance()
    _TIER_STYLE = {
        'live':      ('#0f1f12', '#00cc66', 'LIVE'),
        'cached':    ('#1f1a0a', '#ffaa00', 'CACHED'),
        'synthetic': ('#1f1010', '#ff5544', 'SYNTHETIC'),
    }
    _DATASETS = [
        ('ois_curve',           'OIS CURVE'),
        ('gsec_curve',          'G-SEC CURVE'),
        ('policy_rates',        'POLICY RATES'),
        ('counterparty_credit', 'CP CREDIT'),
        ('mibor_history',       'MIBOR HISTORY'),
    ]
    # Headline reflects the CORE market data (curves + policy); the expander
    # below gives the full per-dataset breakdown including secondary feeds.
    _CORE = ('ois_curve', 'gsec_curve', 'policy_rates')
    _order = {'live': 0, 'cached': 1, 'synthetic': 2}
    _present = [_prov[k]['tier'] for k in _CORE if k in _prov]
    _overall = max(_present, key=lambda t: _order[t]) if _present else 'synthetic'
    _bg, _fg, _lbl = _TIER_STYLE[_overall]
    _src = _prov.get('ois_curve', {}).get('source', '')
    _suffix = f" &middot; {_src}" if (_overall == 'live' and _src) else ''
    st.markdown(f"""<div style='background:{_bg};border:1px solid {_fg};
        border-radius:4px;text-align:center;color:{_fg};font-size:0.62rem;
        font-weight:700;letter-spacing:.10em;padding:4px;margin:2px 0 6px'>
        &#9679; DATA: {_lbl}{_suffix}</div>""", unsafe_allow_html=True)

    with st.expander("DATA SOURCES", expanded=False):
        for _key, _label in _DATASETS:
            _p = _prov.get(_key)
            if not _p:
                continue
            _dot = _TIER_STYLE[_p['tier']][1]
            _tlbl = _TIER_STYLE[_p['tier']][2]
            _ssrc = f" &middot; {_p['source']}" if _p['source'] else ''
            st.markdown(f"""<div style='font-size:0.58rem;color:#8899aa;
                display:flex;justify-content:space-between;gap:6px;padding:1px 0'>
                <span>{_label}</span>
                <span style='color:{_dot};font-weight:700'>&#9679; {_tlbl}{_ssrc}</span>
                </div>""", unsafe_allow_html=True)

    if 'current_page' not in st.session_state:
        st.session_state.current_page = "Executive Risk Dashboard"

    current_page = st.session_state.current_page
    current_cat  = next((cat for cat, v in PAGES.items() if current_page in v["pages"]),
                        list(PAGES.keys())[0])

    # Category dropdown
    selected_cat = st.selectbox(
        "MODULE",
        list(PAGES.keys()),
        index=list(PAGES.keys()).index(current_cat),
        format_func=lambda c: f"[{PAGES[c]['fkey']}]  {c}"
    )

    pages_in_cat = PAGES[selected_cat]["pages"]

    # Page dropdown
    default_idx = pages_in_cat.index(current_page) if current_page in pages_in_cat else 0
    selected_page = st.selectbox(
        "VIEW",
        pages_in_cat,
        index=default_idx,
        format_func=lambda p: _PAGE_LABELS.get(p, p)
    )

    if selected_page != st.session_state.current_page:
        st.session_state.current_page = selected_page
        st.rerun()

    page = st.session_state.current_page

    st.markdown("<hr style='border-color:#1e2830;margin:8px 0'>", unsafe_allow_html=True)
    st.markdown("""<div style='color:#ff6600;font-size:0.62rem;font-weight:700;
        text-transform:uppercase;letter-spacing:.12em;padding:4px 0 2px'>
        TRADE PARAMETERS</div>""", unsafe_allow_html=True)

    counterparties = get_counterparty_data()
    cpty_selected = st.selectbox(
        "COUNTERPARTY",
        counterparties['counterparty'].tolist(),
        index=0
    )

    notional  = st.number_input("NOTIONAL (₹ CR)", value=500.0,
                                 min_value=10.0, max_value=10000.0, step=50.0)
    fixed_rate = st.number_input("FIXED RATE (%)", value=7.00,
                                  min_value=1.0, max_value=15.0, step=0.05) / 100
    maturity   = st.slider("MATURITY (YRS)", min_value=1, max_value=10, value=5)
    direction  = st.selectbox("DIRECTION", ["Receive Fixed", "Pay Fixed"])

    st.markdown("<hr style='border-color:#1e2830;margin:8px 0'>", unsafe_allow_html=True)
    st.markdown("""<div style='color:#ff6600;font-size:0.62rem;font-weight:700;
        text-transform:uppercase;letter-spacing:.12em;padding:4px 0 2px'>
        HW1F MODEL PARAMS</div>""", unsafe_allow_html=True)

    n_paths  = st.select_slider("MC PATHS", options=[1000, 2000, 5000, 10000], value=2000)
    mean_rev = st.slider("MEAN REVERSION (a)", 0.01, 0.30, 0.10, 0.01)
    vol      = st.slider("VOLATILITY (σ)", 0.005, 0.025, 0.010, 0.001)

    st.markdown("<hr style='border-color:#1e2830;margin:8px 0'>", unsafe_allow_html=True)
    st.markdown(f"""<div style='color:#556677;font-size:0.60rem;text-align:center;
        padding:4px 0;letter-spacing:.06em'>
        XVA ANALYTICS PLATFORM &nbsp;&#9679;&nbsp; JUNE 2026<br>
        BUILD {BUILD_ID} &nbsp;&#9679;&nbsp; HULL-WHITE 1F</div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# UI Helper functions
# ─────────────────────────────────────────────────────────────
def section_header(title: str, tooltip: str = ""):
    tip = f'<span class="bbg-tooltip">&nbsp;?&nbsp;<span class="bbg-tooltiptext">{tooltip}</span></span>' if tooltip else ""
    st.markdown(f'<div class="section-header">{title}{tip}</div>', unsafe_allow_html=True)

# Monotonic counter so every export_strip() on a page gets unique widget keys.
_EXPORT_SEQ = {'n': 0}


def _session_snapshot() -> dict:
    """Default export payload: the live market context + selected risk inputs.

    Used whenever a page calls export_strip() without passing its own data, so
    the CSV/PDF buttons always export something real and relevant.
    """
    sections: dict = {}
    try:
        ois, gsec, _cptys, _port, policy = load_market_data()
        sections['OIS Curve']    = ois
        sections['G-Sec Curve']  = gsec
        sections['Policy Rates'] = pd.DataFrame([policy])
    except Exception:
        pass
    g = globals()
    params = {k: g.get(k) for k in
              ('cpty_selected', 'notional', 'fixed_rate', 'maturity',
               'direction', 'n_paths', 'mean_rev', 'vol')
              if g.get(k) is not None}
    if params:
        sections['Trade Parameters'] = pd.DataFrame([params])
    if not sections:
        sections['Export'] = pd.DataFrame({'note': ['No data available']})
    return sections


def _sections_to_csv(sections: dict) -> str:
    """Flatten one or more named DataFrames into a single annotated CSV."""
    parts = []
    for name, df in sections.items():
        parts.append(f"# {name}")
        parts.append(df.to_csv(index=False).rstrip())
        parts.append("")
    return "\n".join(parts).strip() + "\n"


@st.cache_data(show_spinner=False, max_entries=64)
def _csv_to_pdf(csv_text: str, title: str) -> bytes:
    """Render CSV content as a paginated monospace PDF (matplotlib = cloud-safe).

    Cached on the CSV text so the PDF is only built once per unique dataset
    rather than on every Streamlit rerun.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    lines = csv_text.splitlines() or ['(empty)']
    per_page = 46
    stamp = datetime.now().strftime('Generated %Y-%m-%d %H:%M IST')
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for start in range(0, len(lines), per_page):
            chunk = lines[start:start + per_page]
            fig = plt.figure(figsize=(8.27, 11.69))  # A4 portrait
            fig.patch.set_facecolor('white')
            fig.text(0.06, 0.965, (title or 'XVA Engine Export'),
                     fontsize=14, fontweight='bold', color='#cc5200')
            fig.text(0.06, 0.945, stamp, fontsize=8, color='#555555')
            fig.text(0.06, 0.915, "\n".join(chunk), fontsize=7,
                     family='monospace', va='top')
            pdf.savefig(fig)
            plt.close(fig)
    return buf.getvalue()


# ── Per-page export collection ─────────────────────────────────────────
# export_strip() reserves the CSV/PDF buttons at the top of a page. As the
# page then renders Plotly charts / tables / metrics, those are auto-captured
# (via the wrappers below) into _EXPORT['sections']. flush_export() at the end
# of the script binds that page-specific data to the buttons — so every page
# exports exactly what it shows, not a shared snapshot.
_EXPORT = {'slot': None, 'sections': {}, 'metrics': [], 'filename': 'xva_export', 'title': ''}


def _slug(text: str) -> str:
    out = ''.join(c.lower() if c.isalnum() else '_' for c in str(text))
    while '__' in out:
        out = out.replace('__', '_')
    return out.strip('_') or 'export'


def export_strip(filename: str = None, title: str = None):
    """Reserve the page's CSV/PDF export buttons; data is bound at flush time."""
    pg = globals().get('page', 'XVA Export')
    _EXPORT['slot'] = st.empty()
    _EXPORT['sections'] = {}
    _EXPORT['metrics'] = []
    _EXPORT['filename'] = filename or f"xva_{_slug(pg)}"
    _EXPORT['title'] = title or pg
    # Buttons are bound to the page's captured data by flush_export() at the
    # end of the run; the reserved slot stays empty until then.


def add_export(name, df):
    """Register a DataFrame (or dict / Styler) for the current page's export."""
    try:
        if df is None:
            return
        if hasattr(df, 'data') and hasattr(df.data, 'to_csv'):   # pandas Styler
            df = df.data
        if hasattr(df, 'to_csv'):
            _EXPORT['sections'][str(name)] = df
        elif isinstance(df, dict):
            _EXPORT['sections'][str(name)] = pd.DataFrame([df])
    except Exception:
        pass


def _fig_to_frames(fig) -> dict:
    """Extract each Plotly trace's plotted data into named DataFrames."""
    frames = {}
    try:
        base = ''
        if getattr(fig.layout, 'title', None) and fig.layout.title.text:
            base = fig.layout.title.text
    except Exception:
        base = ''
    base = base or 'Chart'
    traces = list(getattr(fig, 'data', []) or [])
    for i, tr in enumerate(traces[:12]):          # cap traces (e.g. MC path bundles)
        name = (getattr(tr, 'name', None) or f'series{i+1}')
        d = {}
        for axis in ('x', 'y', 'z'):
            v = getattr(tr, axis, None)
            if v is not None and np.ndim(v) == 1 and len(v) > 0:
                d[axis] = list(v)[:2000]              # cap rows
        if not d:
            continue
        maxlen = max(len(v) for v in d.values())
        for k in d:
            if len(d[k]) < maxlen:
                d[k] = list(d[k]) + [None] * (maxlen - len(d[k]))
        key = f"{base} · {name}" if len(traces) > 1 else base
        frames[key] = pd.DataFrame(d)
    return frames


def _register_fig(fig):
    for name, frame in _fig_to_frames(fig).items():
        uniq, n = name, 2
        while uniq in _EXPORT['sections']:
            uniq = f"{name} ({n})"; n += 1
        _EXPORT['sections'][uniq] = frame


def _render_export():
    """Render (or re-render) the CSV/PDF buttons into the reserved slot."""
    slot = _EXPORT['slot']
    if slot is None:
        return
    sections = dict(_EXPORT['sections'])
    if _EXPORT['metrics']:
        sections = {'Key Metrics': pd.DataFrame(_EXPORT['metrics']), **sections}
    if not sections:
        sections = _session_snapshot()

    csv_text = _sections_to_csv(sections)
    title = _EXPORT['title']
    filename = _EXPORT['filename']
    freshness = datetime.now().strftime("MKTDATA: %H:%M:%S IST")

    with slot.container():
        c1, c2, c3 = st.columns([1, 1, 5])
        with c1:
            st.download_button("CSV", data=csv_text.encode('utf-8'),
                               file_name=f"{filename}.csv", mime="text/csv",
                               key="exp_csv", use_container_width=True)
        with c2:
            try:
                pdf_bytes = _csv_to_pdf(csv_text, title)
                st.download_button("PDF", data=pdf_bytes,
                                   file_name=f"{filename}.pdf", mime="application/pdf",
                                   key="exp_pdf", use_container_width=True)
            except Exception:
                st.download_button("PDF", data=csv_text.encode('utf-8'),
                                   file_name=f"{filename}.csv", mime="text/csv",
                                   key="exp_pdf", use_container_width=True)
        with c3:
            st.markdown(f"<span class='freshness-badge'>{freshness}</span>",
                        unsafe_allow_html=True)


def flush_export():
    """Re-render the page's export buttons with all captured data. Called once
    at the end of the script run."""
    if _EXPORT['slot'] is not None:
        _render_export()


# Capture chart / table renders into the active page's export payload.
_orig_plotly_chart = st.plotly_chart
def _plotly_chart_capture(fig, *args, **kwargs):
    try:
        _register_fig(fig)
    except Exception:
        pass
    return _orig_plotly_chart(fig, *args, **kwargs)
st.plotly_chart = _plotly_chart_capture

_orig_dataframe = st.dataframe
def _dataframe_capture(data=None, *args, **kwargs):
    try:
        add_export(f"Table {len(_EXPORT['sections']) + 1}", data)
    except Exception:
        pass
    return _orig_dataframe(data, *args, **kwargs)
st.dataframe = _dataframe_capture

def _apply_bbg_chart(fig, title="", range_selector=False):
    """Apply Bloomberg Plotly layout to a figure in place."""
    updates = dict(**PLOTLY_LAYOUT, title=title)
    if range_selector:
        updates['xaxis'] = dict(PLOTLY_LAYOUT['xaxis'], rangeselector=_RANGESELECTOR)
    fig.update_layout(**updates)
    fig.update_xaxes(showgrid=True, gridcolor='#1a2230', zeroline=False,
                     showline=True, linecolor='#243040', mirror=False)
    fig.update_yaxes(showgrid=True, gridcolor='#1a2230', zeroline=False,
                     showline=True, linecolor='#243040', mirror=False)
    return fig

# ─────────────────────────────────────────────────────────────
# Build curves and run simulation
# ─────────────────────────────────────────────────────────────
ois_curve, gsec_curve = build_curves()

sim_result = run_simulation(
    ois_curve, notional, fixed_rate, float(maturity), direction,
    n_paths, mean_rev, vol
)

time_grid = sim_result['time_grid']
rate_paths = sim_result['rate_paths']
mtm_paths = sim_result['mtm_paths']
metrics = sim_result['metrics']

# Get counterparty data for selected counterparty
cpty_row = counterparties[counterparties['counterparty'] == cpty_selected].iloc[0]
credit_curve = CreditCurve(cpty_row['cds_spread_bps'], cpty_row['recovery_rate'])

# Swap pricer
swap = SwapPricer(notional, fixed_rate, float(maturity), direction)

# Reset the export slot each run; pages that call export_strip() set it again.
_EXPORT['slot'] = None

# ─────────────────────────────────────────────────────────────
# PAGE 1: Single Trade Summary
# ─────────────────────────────────────────────────────────────
if page == "Trade Analytics":
    st.markdown("# Trade Analytics")
    st.markdown(f"<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                f"CPTY: <span style='color:#e0e0e0'>{cpty_selected}</span> &nbsp;|&nbsp; "
                f"DIR: <span style='color:#e0e0e0'>{direction.upper()}</span> &nbsp;|&nbsp; "
                f"NTL: <span style='color:#e0e0e0'>₹{notional:.0f} CR</span> &nbsp;|&nbsp; "
                f"MAT: <span style='color:#e0e0e0'>{maturity}Y</span> &nbsp;|&nbsp; "
                f"RATE: <span style='color:#ff6600'>{fixed_rate*100:.2f}%</span></div>",
                unsafe_allow_html=True)
    export_strip()

    # Compute XVA components
    mtm_value    = swap.mtm(ois_curve)
    par_rate_val = swap.par_rate(ois_curve)
    dv01_val     = swap.dv01(ois_curve)

    cva_engine = CVAEngine(ois_curve)
    cva_val    = cva_engine.compute_cva(metrics['EE'], time_grid, credit_curve)

    own_curve = CreditCurve(40.0)
    dva_val   = cva_engine.compute_dva(metrics['ENE'], time_grid, own_curve)

    fva_engine = FVAEngine(ois_curve, cpty_row['funding_spread_bps'])
    fva_result = fva_engine.compute_fva(metrics['EE'], metrics['ENE'], time_grid)

    kva_engine = KVAEngine(ois_curve)
    kva_result = kva_engine.compute_kva_from_exposure(
        metrics['EE'], time_grid, cpty_row['risk_weight']
    )

    xva_adjusted = mtm_value - cva_val + dva_val - abs(fva_result['FVA']) - kva_result['KVA']

    section_header("MARKET RISK METRICS", "Key rate sensitivities and mark-to-market for the active trade")
    cols = st.columns(4)
    cols[0].metric("PORTFOLIO MTM", f"₹{mtm_value:.4f} CR",
                    delta=f"PAR: {par_rate_val*100:.2f}%", accent="blue")
    cols[1].metric("DV01", f"₹{dv01_val:.4f} CR",
                    delta=f"PV01: {swap.pv01(ois_curve):.4f}", accent="amber")
    cols[2].metric("EPE", f"₹{metrics['EPE']:.4f} CR", accent="blue")
    cols[3].metric("EEPE", f"₹{metrics['EEPE']:.4f} CR", accent="blue")

    section_header("XVA COMPONENTS", "Credit, Funding and Capital valuation adjustments")
    cols2 = st.columns(5)
    cols2[0].metric("CVA", f"₹{cva_val:.4f} CR", accent="red")
    cols2[1].metric("DVA", f"₹{dva_val:.4f} CR", accent="green")
    cols2[2].metric("FVA", f"₹{fva_result['FVA']:.4f} CR", accent="amber")
    cols2[3].metric("KVA", f"₹{kva_result['KVA']:.4f} CR", accent="amber")
    cols2[4].metric("XVA-ADJ MTM", f"₹{xva_adjusted:.4f} CR",
                     delta=f"{(xva_adjusted - mtm_value):.4f} CR ADJ", accent="blue")

    section_header("YIELD CURVES")
    col_curve1, col_curve2 = st.columns(2)

    with col_curve1:
        plot_tenors = np.linspace(0.1, 10.0, 100)
        zero_rates  = ois_curve.zero_rate_array(plot_tenors) * 100
        fwd_rates   = np.array([ois_curve.instantaneous_forward(t) for t in plot_tenors]) * 100

        fig_curves = go.Figure()
        fig_curves.add_trace(go.Scatter(
            x=plot_tenors, y=zero_rates, name='OIS ZERO RATE', mode='lines',
            line=dict(color=COLORS['EE'], width=2.5),
            hovertemplate='<b>Tenor:</b> %{x:.2f}Y<br><b>Zero Rate:</b> %{y:.4f}%<extra></extra>'
        ))
        fig_curves.add_trace(go.Scatter(
            x=plot_tenors, y=fwd_rates, name='FORWARD RATE', mode='lines',
            line=dict(color=COLORS['accent'], width=2, dash='dash'),
            hovertemplate='<b>Tenor:</b> %{x:.2f}Y<br><b>Fwd Rate:</b> %{y:.4f}%<extra></extra>'
        ))
        _apply_bbg_chart(fig_curves, 'INR OIS ZERO & FORWARD CURVES')
        fig_curves.update_xaxes(title_text='TENOR (YEARS)')
        fig_curves.update_yaxes(title_text='RATE (%)')
        st.plotly_chart(fig_curves, use_container_width=True)

    with col_curve2:
        df_values = ois_curve.df_array(plot_tenors)
        fig_df = go.Figure()
        fig_df.add_trace(go.Scatter(
            x=plot_tenors, y=df_values, name='DISCOUNT FACTOR', mode='lines',
            line=dict(color=COLORS['success'], width=2.5),
            fill='tozeroy', fillcolor='rgba(0,204,102,0.08)',
            hovertemplate='<b>Tenor:</b> %{x:.2f}Y<br><b>DF:</b> %{y:.6f}<extra></extra>'
        ))
        _apply_bbg_chart(fig_df, 'OIS DISCOUNT FACTOR CURVE')
        fig_df.update_xaxes(title_text='TENOR (YEARS)')
        fig_df.update_yaxes(title_text='DISCOUNT FACTOR')
        st.plotly_chart(fig_df, use_container_width=True)

    section_header("OIS VS G-SEC SOVEREIGN BASIS")
    spread_tenors = np.linspace(0.5, 10.0, 50)
    spreads = gsec_curve.spread_over_ois(ois_curve, spread_tenors) * 10000

    fig_spread = go.Figure()
    bar_colors = [COLORS['success'] if s >= 0 else COLORS['danger_bright'] for s in spreads]
    fig_spread.add_trace(go.Bar(
        x=spread_tenors, y=spreads, name='G-SEC / OIS SPREAD',
        marker=dict(color=bar_colors),
        hovertemplate='<b>Tenor:</b> %{x:.2f}Y<br><b>Spread:</b> %{y:.1f} bps<extra></extra>'
    ))
    _apply_bbg_chart(fig_spread, 'G-SEC VS OIS ZERO RATE SPREAD (SOVEREIGN BASIS)')
    fig_spread.update_xaxes(title_text='TENOR (YEARS)')
    fig_spread.update_yaxes(title_text='SPREAD (BPS)')
    st.plotly_chart(fig_spread, use_container_width=True)

    with st.expander("CASH FLOW SCHEDULE"):
        cf_df = swap.cash_flow_schedule(ois_curve)
        st.dataframe(cf_df.style.format({
            'payment_date_years': '{:.2f}', 'accrual_fraction': '{:.4f}',
            'fixed_cf_cr': '{:.4f}', 'float_cf_cr': '{:.4f}',
            'net_cf_cr': '{:.4f}', 'discount_factor': '{:.6f}', 'pv_net_cf_cr': '{:.4f}',
        }), use_container_width=True)

    with st.expander("KEY RATE DV01 LADDER"):
        kr_dv01 = swap.key_rate_dv01(ois_curve)
        kr_df = pd.DataFrame({'Tenor': list(kr_dv01.keys()), 'KR-DV01 (₹ Cr)': list(kr_dv01.values())})
        fig_kr = go.Figure()
        krd_colors = [COLORS['success'] if v >= 0 else COLORS['danger_bright'] for v in kr_df['KR-DV01 (₹ Cr)']]
        fig_kr.add_trace(go.Bar(
            x=kr_df['Tenor'], y=kr_df['KR-DV01 (₹ Cr)'],
            marker=dict(color=krd_colors),
            hovertemplate='<b>Tenor:</b> %{x}<br><b>KR-DV01:</b> ₹%{y:.4f} Cr<extra></extra>'
        ))
        _apply_bbg_chart(fig_kr, 'KEY RATE DV01 LADDER')
        fig_kr.update_xaxes(title_text='TENOR')
        fig_kr.update_yaxes(title_text='KR-DV01 (₹ CR)')
        st.plotly_chart(fig_kr, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# PAGE 2: Exposure Analytics
# ─────────────────────────────────────────────────────────────
elif page == "Counterparty Exposure Analytics":
    st.markdown("# Counterparty Exposure Analytics")
    st.markdown(f"<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                f"MC PATHS: <span style='color:#ff6600'>{n_paths:,}</span> &nbsp;|&nbsp; "
                f"HORIZON: <span style='color:#e0e0e0'>{maturity}Y</span> &nbsp;|&nbsp; "
                f"HW1F: a=<span style='color:#e0e0e0'>{mean_rev}</span> "
                f"σ=<span style='color:#e0e0e0'>{vol}</span></div>", unsafe_allow_html=True)
    export_strip()

    section_header("EXPOSURE PROFILE", "Expected Exposure (EE), Expected Positive/Negative Exposure and Potential Future Exposure profiles from the Monte Carlo simulation")

    fig_exposure = go.Figure()
    fig_exposure.add_trace(go.Scatter(
        x=time_grid, y=metrics['PFE'], name='PFE 99%', mode='lines',
        line=dict(color='#ff2222', width=1.5, dash='dot'),
        hovertemplate='<b>PFE 99%</b><br>t=%{x:.2f}Y  val=₹%{y:.4f} Cr<extra></extra>'
    ))
    fig_exposure.add_trace(go.Scatter(
        x=time_grid, y=metrics['PFE'], name='PFE 95%', mode='lines',
        line=dict(color=COLORS['PFE'], width=2),
        hovertemplate='<b>PFE 95%</b><br>t=%{x:.2f}Y  val=₹%{y:.4f} Cr<extra></extra>'
    ))
    fig_exposure.add_trace(go.Scatter(
        x=np.concatenate([time_grid, time_grid[::-1]]),
        y=np.concatenate([metrics['PFE'], metrics['EE'][::-1]]),
        fill='toself', fillcolor='rgba(255,68,68,0.07)',
        line=dict(color='rgba(0,0,0,0)'), showlegend=False, name='PFE band'
    ))
    fig_exposure.add_trace(go.Scatter(
        x=time_grid, y=metrics['EE'], name='EE', mode='lines',
        line=dict(color=COLORS['EE'], width=2.5),
        hovertemplate='<b>EE</b><br>t=%{x:.2f}Y  val=₹%{y:.4f} Cr<extra></extra>'
    ))
    fig_exposure.add_trace(go.Scatter(
        x=time_grid, y=metrics['ENE'], name='ENE', mode='lines',
        line=dict(color=COLORS['ENE'], width=1.5, dash='dot'),
        hovertemplate='<b>ENE</b><br>t=%{x:.2f}Y  val=₹%{y:.4f} Cr<extra></extra>'
    ))
    _apply_bbg_chart(fig_exposure, 'EXPOSURE PROFILE OVER TIME')
    fig_exposure.update_layout(hovermode='x unified')
    fig_exposure.update_xaxes(title_text='TIME (YEARS)')
    fig_exposure.update_yaxes(title_text='EXPOSURE (₹ CR)')
    st.plotly_chart(fig_exposure, use_container_width=True)

    col_fan, col_hist = st.columns(2)

    with col_fan:
        section_header("SIMULATED RATE PATHS")
        n_show = min(200, n_paths)
        fig_fan = go.Figure()
        for i in range(n_show):
            fig_fan.add_trace(go.Scatter(
                x=time_grid, y=rate_paths[i] * 100, mode='lines',
                line=dict(color='#00aaff', width=0.4), opacity=0.12, showlegend=False,
            ))
        mean_rate = np.mean(rate_paths, axis=0) * 100
        fig_fan.add_trace(go.Scatter(
            x=time_grid, y=mean_rate, name='MEAN RATE', mode='lines',
            line=dict(color=COLORS['EPE'], width=2.5),
            hovertemplate='<b>Mean Rate:</b> %{y:.4f}%<extra></extra>'
        ))
        _apply_bbg_chart(fig_fan, f'HW1F RATE PATHS ({n_show} SHOWN)')
        fig_fan.update_xaxes(title_text='TIME (YEARS)')
        fig_fan.update_yaxes(title_text='SHORT RATE (%)')
        st.plotly_chart(fig_fan, use_container_width=True)

    with col_hist:
        section_header("MTM DISTRIBUTION")
        horizon_step = st.slider("HORIZON (STEP INDEX)", 1, len(time_grid)-1,
                                  len(time_grid)//2, key='hist_horizon')
        mtm_at_t = mtm_paths[:, horizon_step]
        ee_val   = metrics['EE'][horizon_step]
        pfe_val  = metrics['PFE'][horizon_step]

        fig_hist = go.Figure()
        fig_hist.add_trace(go.Histogram(
            x=mtm_at_t, nbinsx=50,
            name=f'MTM @ t={time_grid[horizon_step]:.1f}Y',
            marker=dict(color=COLORS['EE'], line=dict(color='#243040', width=0.5)),
            opacity=0.8,
            hovertemplate='<b>MTM bin:</b> %{x:.2f}<br><b>Count:</b> %{y}<extra></extra>'
        ))
        fig_hist.add_vline(x=ee_val,  line_color=COLORS['success'],  line_dash='dash',
                           annotation_text=f'EE={ee_val:.2f}',
                           annotation_font=dict(color=COLORS['success'], size=9))
        fig_hist.add_vline(x=pfe_val, line_color=COLORS['danger_bright'], line_dash='dash',
                           annotation_text=f'PFE={pfe_val:.2f}',
                           annotation_font=dict(color=COLORS['danger_bright'], size=9))
        fig_hist.add_vline(x=0, line_color='#556677', line_width=1)
        _apply_bbg_chart(fig_hist, f'MTM DISTRIBUTION @ t={time_grid[horizon_step]:.1f}Y')
        fig_hist.update_xaxes(title_text='MTM (₹ CR)')
        fig_hist.update_yaxes(title_text='FREQUENCY')
        st.plotly_chart(fig_hist, use_container_width=True)

    section_header("COLLATERALISED VS UNCOLLATERALISED EXPOSURE", "Expected Exposure under different CSA/margin scenarios")

    csa_scenarios = get_csa_scenarios()
    csa_results   = compare_csa_scenarios(mtm_paths, time_grid, csa_scenarios)
    csa_colors    = [COLORS['danger_bright'], COLORS['EPE'], COLORS['EE'], COLORS['ENE']]

    fig_csa = go.Figure()
    for idx, (name, res) in enumerate(csa_results.items()):
        fig_csa.add_trace(go.Scatter(
            x=time_grid, y=res['EE'],
            name=f'{name.upper()} (EPE={res["EPE"]:.3f})',
            mode='lines',
            line=dict(color=csa_colors[idx % len(csa_colors)], width=2),
            hovertemplate=f'<b>{name}</b><br>t=%{{x:.2f}}Y  EE=₹%{{y:.4f}} Cr<extra></extra>'
        ))
    _apply_bbg_chart(fig_csa, 'EXPECTED EXPOSURE UNDER CSA SCENARIOS')
    fig_csa.update_layout(hovermode='x unified')
    fig_csa.update_xaxes(title_text='TIME (YEARS)')
    fig_csa.update_yaxes(title_text='EXPECTED EXPOSURE (₹ CR)')
    st.plotly_chart(fig_csa, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# PAGE 3: Credit Analytics
# ─────────────────────────────────────────────────────────────
elif page == "Credit Risk Analytics":
    st.markdown("# Credit Risk Analytics")

    section_header("COUNTERPARTY CREDIT SUMMARY", "CDS spreads, hazard rates, survival probabilities and recovery rates by counterparty")
    export_strip()

    cpty_data = get_counterparty_data()
    cpty_display = cpty_data.copy()
    cpty_display['hazard_rate_pct'] = (cpty_display['cds_spread_bps'] / 10000 /
                                        (1 - cpty_display['recovery_rate'])) * 100
    cpty_display['survival_5y'] = np.exp(
        -(cpty_display['cds_spread_bps'] / 10000 /
          (1 - cpty_display['recovery_rate'])) * 5.0
    ) * 100

    _rating_color = {"AAA": "rating-aaa", "AA": "rating-aa", "A": "rating-a",
                     "BBB": "rating-bbb", "BB": "num-warn", "B": "num-neg"}

    def _credit_table_html(df):
        rows = ""
        for _, r in df.iterrows():
            rc = _rating_color.get(str(r['rating']), "")
            sp_cls = "num-neg" if r['cds_spread_bps'] > 200 else "num-warn" if r['cds_spread_bps'] > 80 else "num-pos"
            rows += f"""<tr>
              <td>{r['counterparty']}</td>
              <td class="{rc}">{r['rating']}</td>
              <td class="{sp_cls}">{r['cds_spread_bps']:.0f}</td>
              <td>{r['recovery_rate']:.0%}</td>
              <td class="num-warn">{r['hazard_rate_pct']:.2f}%</td>
              <td class="{'num-pos' if r['survival_5y']>80 else 'num-warn' if r['survival_5y']>60 else 'num-neg'}">{r['survival_5y']:.1f}%</td>
            </tr>"""
        return f"""<div class="bbg-table-wrap"><table class="bbg-table">
          <thead><tr>
            <th>COUNTERPARTY</th><th>RATING</th><th>CDS (BPS)</th>
            <th>RECOVERY</th><th>HAZARD RATE</th><th>SURVIVAL 5Y</th>
          </tr></thead><tbody>{rows}</tbody></table></div>"""

    st.markdown(_credit_table_html(cpty_display), unsafe_allow_html=True)

    col_surv, col_hz = st.columns(2)

    with col_surv:
        section_header("SURVIVAL PROBABILITY CURVES")
        t_plot = np.linspace(0, 10, 100)
        surv_palette = [COLORS['EE'], COLORS['EPE'], COLORS['ENE'],
                        COLORS['PFE'], '#cc66ff', '#ff9933']
        fig_surv = go.Figure()
        for i, row in cpty_data.iterrows():
            cc = CreditCurve(row['cds_spread_bps'], row['recovery_rate'])
            sp = cc.survival_probability_array(t_plot) * 100
            fig_surv.add_trace(go.Scatter(
                x=t_plot, y=sp,
                name=f"{row['counterparty'].upper()} ({row['cds_spread_bps']}bps)",
                mode='lines',
                line=dict(color=surv_palette[i % len(surv_palette)], width=2),
                hovertemplate=f"<b>{row['counterparty']}</b><br>t=%{{x:.2f}}Y  SP=%{{y:.1f}}%<extra></extra>"
            ))
        _apply_bbg_chart(fig_surv, 'COUNTERPARTY SURVIVAL PROBABILITIES')
        fig_surv.update_layout(hovermode='x unified')
        fig_surv.update_xaxes(title_text='TIME (YEARS)')
        fig_surv.update_yaxes(title_text='SURVIVAL PROB (%)')
        st.plotly_chart(fig_surv, use_container_width=True)

    with col_hz:
        section_header("IMPLIED HAZARD RATES")
        hz_colors = [COLORS['success'] if h < 2 else COLORS['EPE'] if h < 5 else COLORS['danger_bright']
                     for h in cpty_display['hazard_rate_pct']]
        fig_hz = go.Figure()
        fig_hz.add_trace(go.Bar(
            x=cpty_data['counterparty'].str.upper(),
            y=cpty_display['hazard_rate_pct'],
            marker=dict(color=hz_colors),
            text=[f'{h:.2f}%' for h in cpty_display['hazard_rate_pct']],
            textposition='outside',
            textfont=dict(family=_MONO, color='#e0e0e0', size=9),
            hovertemplate='<b>%{x}</b><br>Hazard Rate: %{y:.2f}%<extra></extra>'
        ))
        _apply_bbg_chart(fig_hz, 'IMPLIED HAZARD RATES BY COUNTERPARTY')
        fig_hz.update_xaxes(title_text='COUNTERPARTY')
        fig_hz.update_yaxes(title_text='HAZARD RATE (%)')
        st.plotly_chart(fig_hz, use_container_width=True)

    section_header("CVA SENSITIVITY TO CDS SPREAD", "CVA as a function of counterparty CDS spread — holding exposure constant")

    cva_engine   = CVAEngine(ois_curve)
    spread_range = np.arange(10, 800, 10)
    cva_values   = [cva_engine.compute_cva(metrics['EE'], time_grid,
                    CreditCurve(s, cpty_row['recovery_rate'])) for s in spread_range]

    current_cva = cva_engine.compute_cva(metrics['EE'], time_grid, credit_curve)

    fig_cva_sens = go.Figure()
    fig_cva_sens.add_trace(go.Scatter(
        x=spread_range, y=cva_values, name='CVA', mode='lines',
        line=dict(color=COLORS['danger_bright'], width=2.5),
        fill='tozeroy', fillcolor='rgba(204,34,0,0.08)',
        hovertemplate='<b>CDS:</b> %{x} bps<br><b>CVA:</b> ₹%{y:.4f} Cr<extra></extra>'
    ))
    fig_cva_sens.add_trace(go.Scatter(
        x=[cpty_row['cds_spread_bps']], y=[current_cva],
        name=f'{cpty_selected.upper()} ({cpty_row["cds_spread_bps"]}bps)',
        mode='markers',
        marker=dict(color=COLORS['EPE'], size=14, symbol='diamond',
                    line=dict(color='#ffffff', width=1)),
        hovertemplate='<b>Current:</b> %{y:.4f} Cr @ %{x} bps<extra></extra>'
    ))
    _apply_bbg_chart(fig_cva_sens, f'CVA VS CDS SPREAD — {cpty_selected.upper()}')
    fig_cva_sens.update_xaxes(title_text='CDS SPREAD (BPS)')
    fig_cva_sens.update_yaxes(title_text='CVA (₹ CR)')
    st.plotly_chart(fig_cva_sens, use_container_width=True)

    section_header("WRONG-WAY RISK", "CVA impact under different rate-credit correlation assumptions")

    wwr_correlations = [-0.30, 0.0, 0.30, 0.50, 0.70]
    wwr_cva_values   = [current_cva * (1 + rho * (0.8 if rho > 0 else 0.5)) for rho in wwr_correlations]
    wwr_colors       = [COLORS['success'], COLORS['EE'], COLORS['EPE'], COLORS['PFE'], COLORS['danger_bright']]

    fig_wwr = go.Figure()
    fig_wwr.add_trace(go.Bar(
        x=[f'ρ={r:+.2f}' for r in wwr_correlations],
        y=wwr_cva_values,
        marker=dict(color=wwr_colors),
        text=[f'₹{v:.4f}' for v in wwr_cva_values],
        textposition='outside',
        textfont=dict(family=_MONO, color='#e0e0e0', size=9),
        hovertemplate='<b>Correlation:</b> %{x}<br><b>WWR-CVA:</b> ₹%{y:.4f} Cr<extra></extra>'
    ))
    fig_wwr.add_hline(y=current_cva, line_dash='dash', line_color='#556677',
                       annotation_text='INDEP CVA',
                       annotation_font=dict(color='#8899aa', size=9))
    _apply_bbg_chart(fig_wwr, 'CVA UNDER RATE-CREDIT CORRELATION ASSUMPTIONS')
    fig_wwr.update_xaxes(title_text='CORRELATION (ρ)')
    fig_wwr.update_yaxes(title_text='CVA (₹ CR)')
    st.plotly_chart(fig_wwr, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# PAGE 4: Capital Analytics
# ─────────────────────────────────────────────────────────────
elif page == "Regulatory Capital Analytics":
    st.markdown("# Regulatory Capital Analytics")

    # ── SA-CCR Computation ──
    st.markdown("### SA-CCR — Exposure at Default")

    calculator = SACCRCalculator()
    trade_addon = calculator.compute_trade_addon(
        notional=notional, maturity=float(maturity),
        direction=direction
    )

    mtm_val = swap.mtm(ois_curve)
    rc = max(mtm_val, 0.0)
    ead = 1.4 * (rc + trade_addon['trade_addon'])
    rw = cpty_row['risk_weight']
    rwa = ead * rw
    capital_req = rwa * 0.105

    section_header("SA-CCR EAD BREAKDOWN", "Standardised Approach CCR — Basel III Exposure at Default")
    export_strip()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("REPLACEMENT COST", f"₹{rc:.4f} CR", accent="blue")
    col2.metric("PFE ADD-ON", f"₹{trade_addon['trade_addon']:.4f} CR", accent="amber")
    col3.metric("EAD (α=1.4)", f"₹{ead:.4f} CR", accent="amber")
    col4.metric("CAPITAL REQ", f"₹{capital_req:.4f} CR", accent="red")

    col_saccr1, col_saccr2 = st.columns(2)

    with col_saccr1:
        section_header("SA-CCR WATERFALL")
        wf_labels = ['MTM', 'RC', 'ADJ NTL', 'SUP DUR', 'PFE ADD-ON', 'α×(RC+PFE)', 'RWA', 'CAPITAL']
        wf_values = [mtm_val, rc, trade_addon['adjusted_notional'],
                     trade_addon['supervisory_duration'],
                     trade_addon['trade_addon'], ead, rwa, capital_req]
        fig_saccr = go.Figure(go.Waterfall(
            x=wf_labels, y=wf_values,
            text=[f'₹{v:.3f}' for v in wf_values],
            textposition='outside',
            textfont=dict(family=_MONO, color='#e0e0e0', size=9),
            connector=dict(line=dict(color='#243040', width=1)),
            increasing=dict(marker=dict(color=COLORS['EE'])),
            decreasing=dict(marker=dict(color=COLORS['danger_bright'])),
            totals=dict(marker=dict(color=COLORS['EPE'])),
            hovertemplate='<b>%{x}</b><br>₹%{y:.4f} Cr<extra></extra>'
        ))
        _apply_bbg_chart(fig_saccr, 'SA-CCR COMPONENT WATERFALL')
        fig_saccr.update_yaxes(title_text='₹ CRORES')
        st.plotly_chart(fig_saccr, use_container_width=True)

    with col_saccr2:
        section_header("RWA BY COUNTERPARTY TYPE")
        rw_data   = get_counterparty_data()
        rw_colors = [COLORS['success'] if w < 0.5 else COLORS['EPE'] if w < 1.0 else COLORS['danger_bright']
                     for w in rw_data['risk_weight']]
        fig_rw = go.Figure()
        fig_rw.add_trace(go.Bar(
            x=rw_data['counterparty'].str.upper(),
            y=rw_data['risk_weight'] * 100,
            marker=dict(color=rw_colors),
            text=[f'{w:.0f}%' for w in rw_data['risk_weight'] * 100],
            textposition='outside',
            textfont=dict(family=_MONO, color='#e0e0e0', size=9),
            hovertemplate='<b>%{x}</b><br>Risk Weight: %{y:.0f}%<extra></extra>'
        ))
        _apply_bbg_chart(fig_rw, 'RBI BASEL III RISK WEIGHTS')
        fig_rw.update_xaxes(title_text='COUNTERPARTY')
        fig_rw.update_yaxes(title_text='RISK WEIGHT (%)')
        st.plotly_chart(fig_rw, use_container_width=True)

    section_header("KVA — CAPITAL VALUATION ADJUSTMENT", "Present value of future capital costs over the life of the trade")

    kva_engine = KVAEngine(ois_curve)
    kva_result = kva_engine.compute_kva_from_exposure(
        metrics['EE'], time_grid, cpty_row['risk_weight']
    )

    col_kva1, col_kva2, col_kva3 = st.columns(3)
    col_kva1.metric("KVA", f"₹{kva_result['KVA']:.4f} CR", accent="red")
    col_kva2.metric("PEAK CAPITAL", f"₹{kva_result['peak_capital_cr']:.4f} CR", accent="amber")
    col_kva3.metric("AVG CAPITAL", f"₹{kva_result['avg_capital_cr']:.4f} CR", accent="amber")

    fig_kva = go.Figure()
    fig_kva.add_trace(go.Scatter(
        x=time_grid, y=kva_result['capital_profile'], name='CAPITAL REQ', mode='lines',
        line=dict(color=COLORS['EPE'], width=2.5),
        fill='tozeroy', fillcolor='rgba(255,170,0,0.08)',
        hovertemplate='<b>Capital:</b> ₹%{y:.4f} Cr<extra></extra>'
    ))
    fig_kva.add_trace(go.Scatter(
        x=time_grid, y=kva_result['ead_profile'], name='EAD PROFILE', mode='lines',
        line=dict(color=COLORS['EE'], width=2, dash='dash'),
        hovertemplate='<b>EAD:</b> ₹%{y:.4f} Cr<extra></extra>'
    ))
    _apply_bbg_chart(fig_kva, f'CAPITAL & EAD PROFILE (RW={rw*100:.0f}%)')
    fig_kva.update_layout(hovermode='x unified')
    fig_kva.update_xaxes(title_text='TIME (YEARS)')
    fig_kva.update_yaxes(title_text='₹ CRORES')
    st.plotly_chart(fig_kva, use_container_width=True)

    with st.expander("SA-CCR TRADE PARAMETERS"):
        params = [
            ('DELTA (δ)', f"{trade_addon['delta']:+.0f}"),
            ('SUPERVISORY DURATION', f"{trade_addon['supervisory_duration']:.4f}"),
            ('ADJUSTED NOTIONAL', f"₹{trade_addon['adjusted_notional']:.2f} Cr"),
            ('EFFECTIVE NOTIONAL', f"₹{trade_addon['effective_notional']:.2f} Cr"),
            ('MATURITY FACTOR', f"{trade_addon['maturity_factor']:.4f}"),
            ('MATURITY BUCKET', trade_addon['maturity_bucket'].upper()),
            ('SUPERVISORY FACTOR', f"{trade_addon['supervisory_factor']:.4%}"),
            ('TRADE ADD-ON', f"₹{trade_addon['trade_addon']:.4f} Cr"),
        ]
        rows = "".join(f"<tr><td>{p}</td><td>{v}</td></tr>" for p, v in params)
        st.markdown(f"""<div class="bbg-table-wrap"><table class="bbg-table">
          <thead><tr><th>PARAMETER</th><th>VALUE</th></tr></thead>
          <tbody>{rows}</tbody></table></div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# PAGE 5: Stress Testing
# ─────────────────────────────────────────────────────────────
elif page == "Stress & Scenario Analysis":
    st.markdown("# Stress & Scenario Analysis")
    export_strip()

    section_header("RBI RATE SHOCK SCENARIO BUILDER", "Interactive parallel shift to OIS and credit curves")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        rate_shock = st.slider("RATE SHOCK (BPS)", min_value=-200, max_value=300, value=0, step=25)
    with col_s2:
        credit_shock = st.slider("CREDIT SPREAD SHOCK (BPS)", min_value=-50, max_value=500, value=0, step=25)

    shocked_curve  = ois_curve.shift(rate_shock)
    shocked_mtm    = swap.mtm(shocked_curve)
    base_mtm       = swap.mtm(ois_curve)
    shocked_cds    = max(cpty_row['cds_spread_bps'] + credit_shock, 1.0)
    shocked_credit = CreditCurve(shocked_cds, cpty_row['recovery_rate'])
    cva_engine     = CVAEngine(ois_curve)
    shocked_cva    = cva_engine.compute_cva(metrics['EE'], time_grid, shocked_credit)
    base_cva       = cva_engine.compute_cva(metrics['EE'], time_grid, credit_curve)

    section_header("SCENARIO IMPACT")
    cols = st.columns(4)
    mtm_chg = shocked_mtm - base_mtm
    cva_chg = shocked_cva - base_cva
    cols[0].metric("MTM", f"₹{shocked_mtm:.4f} CR",
                    delta=f"{mtm_chg:+.4f} CR", accent="blue")
    cols[1].metric("CVA", f"₹{shocked_cva:.4f} CR",
                    delta=f"{cva_chg:+.4f} CR", accent="red")
    cols[2].metric("CDS SPREAD", f"{shocked_cds:.0f} BPS",
                    delta=f"{credit_shock:+.0f} BPS", accent="amber")
    cols[3].metric("SURVIVAL 5Y",
                    f"{shocked_credit.survival_probability(5)*100:.1f}%",
                    delta=f"{(shocked_credit.survival_probability(5) - credit_curve.survival_probability(5))*100:.2f}%",
                    accent="green")

    section_header("PREDEFINED STRESS SCENARIO MATRIX")
    stress_scenarios = get_stress_scenarios()
    stress_results   = []
    for _, scenario in stress_scenarios.iterrows():
        sc_curve  = ois_curve.shift(scenario['rate_shock_bps'])
        sc_mtm    = swap.mtm(sc_curve)
        sc_cds    = max(cpty_row['cds_spread_bps'] + scenario['credit_spread_shock_bps'], 1.0)
        sc_credit = CreditCurve(sc_cds, cpty_row['recovery_rate'])
        sc_cva    = cva_engine.compute_cva(metrics['EE'], time_grid, sc_credit)
        stress_results.append({
            'scenario': scenario['scenario'],
            'description': scenario['description'],
            'rate_shock': f"{scenario['rate_shock_bps']:+d}",
            'credit_shock': f"{scenario['credit_spread_shock_bps']:+d}",
            'mtm': sc_mtm,
            'mtm_chg': sc_mtm - base_mtm,
            'cva': sc_cva,
            'cva_chg': sc_cva - base_cva,
        })

    def _stress_table(results):
        rows = ""
        for r in results:
            mc = "num-pos" if r['mtm_chg'] >= 0 else "num-neg"
            cc = "num-neg" if r['cva_chg'] >= 0 else "num-pos"
            rows += f"""<tr>
              <td>{r['scenario']}</td>
              <td>{r['description']}</td>
              <td>{r['rate_shock']} bps</td>
              <td>{r['credit_shock']} bps</td>
              <td>₹{r['mtm']:.4f}</td>
              <td class="{mc}">{r['mtm_chg']:+.4f}</td>
              <td>₹{r['cva']:.4f}</td>
              <td class="{cc}">{r['cva_chg']:+.4f}</td>
            </tr>"""
        return f"""<div class="bbg-table-wrap"><table class="bbg-table">
          <thead><tr>
            <th>SCENARIO</th><th>DESCRIPTION</th><th>RATE Δ</th><th>CDS Δ</th>
            <th>MTM (₹CR)</th><th>MTM CHG</th><th>CVA (₹CR)</th><th>CVA CHG</th>
          </tr></thead><tbody>{rows}</tbody></table></div>"""

    st.markdown(_stress_table(stress_results), unsafe_allow_html=True)

    col_st1, col_st2 = st.columns(2)
    with col_st1:
        section_header("MTM SENSITIVITY — RATE SHOCK")
        rate_range      = np.arange(-200, 350, 25)
        mtm_sensitivity = [swap.mtm(ois_curve.shift(r)) for r in rate_range]
        mtm_colors      = [COLORS['success'] if v >= 0 else COLORS['danger_bright'] for v in mtm_sensitivity]
        fig_mtm_stress  = go.Figure()
        fig_mtm_stress.add_trace(go.Scatter(
            x=rate_range, y=mtm_sensitivity, mode='lines+markers',
            line=dict(color=COLORS['EE'], width=2.5),
            marker=dict(size=4, color=mtm_colors),
            name='MTM',
            hovertemplate='<b>Shock:</b> %{x} bps<br><b>MTM:</b> ₹%{y:.4f} Cr<extra></extra>'
        ))
        fig_mtm_stress.add_vline(x=0, line_dash='dash', line_color='#556677', line_width=1)
        fig_mtm_stress.add_hline(y=0, line_dash='dash', line_color='#556677', line_width=1)
        fig_mtm_stress.add_vline(x=rate_shock, line_dash='dash', line_color=COLORS['danger_bright'],
                                  annotation_text=f'{rate_shock:+d} BPS',
                                  annotation_font=dict(color=COLORS['danger_bright'], size=9))
        _apply_bbg_chart(fig_mtm_stress, 'MTM VS PARALLEL RATE SHOCK')
        fig_mtm_stress.update_xaxes(title_text='RATE SHOCK (BPS)')
        fig_mtm_stress.update_yaxes(title_text='MTM (₹ CR)')
        st.plotly_chart(fig_mtm_stress, use_container_width=True)

    with col_st2:
        section_header("CVA SENSITIVITY — CREDIT SPREAD")
        credit_range    = np.arange(0, 800, 25)
        cva_sensitivity = [cva_engine.compute_cva(metrics['EE'], time_grid,
                            CreditCurve(max(cpty_row['cds_spread_bps'] + c, 1), cpty_row['recovery_rate']))
                           for c in credit_range]
        fig_cva_stress = go.Figure()
        fig_cva_stress.add_trace(go.Scatter(
            x=credit_range + cpty_row['cds_spread_bps'], y=cva_sensitivity,
            mode='lines+markers',
            line=dict(color=COLORS['danger_bright'], width=2.5),
            marker=dict(size=4),
            name='CVA',
            hovertemplate='<b>CDS:</b> %{x} bps<br><b>CVA:</b> ₹%{y:.4f} Cr<extra></extra>'
        ))
        fig_cva_stress.add_vline(x=cpty_row['cds_spread_bps'], line_dash='dash',
                                  line_color='#556677', line_width=1,
                                  annotation_text='BASE',
                                  annotation_font=dict(color='#8899aa', size=9))
        fig_cva_stress.add_vline(x=shocked_cds, line_dash='dash',
                                  line_color=COLORS['danger_bright'],
                                  annotation_text=f'SHOCK +{credit_shock}',
                                  annotation_font=dict(color=COLORS['danger_bright'], size=9))
        _apply_bbg_chart(fig_cva_stress, f'CVA VS CDS SPREAD — {cpty_selected.upper()}')
        fig_cva_stress.update_xaxes(title_text='CDS SPREAD (BPS)')
        fig_cva_stress.update_yaxes(title_text='CVA (₹ CR)')
        st.plotly_chart(fig_cva_stress, use_container_width=True)

    section_header("SHOCKED VS BASE YIELD CURVE")
    plot_tenors = np.linspace(0.1, 10.0, 100)
    fig_shocked = go.Figure()
    fig_shocked.add_trace(go.Scatter(
        x=plot_tenors, y=ois_curve.zero_rate_array(plot_tenors) * 100,
        name='BASE OIS', mode='lines',
        line=dict(color=COLORS['EE'], width=2.5),
        hovertemplate='<b>Base:</b> %{y:.4f}%<extra></extra>'
    ))
    fig_shocked.add_trace(go.Scatter(
        x=plot_tenors, y=shocked_curve.zero_rate_array(plot_tenors) * 100,
        name=f'SHOCKED ({rate_shock:+}bps)', mode='lines',
        line=dict(color=COLORS['danger_bright'], width=2.5, dash='dash'),
        hovertemplate='<b>Shocked:</b> %{y:.4f}%<extra></extra>'
    ))
    _apply_bbg_chart(fig_shocked, 'OIS ZERO CURVE — BASE VS SHOCKED')
    fig_shocked.update_layout(hovermode='x unified')
    fig_shocked.update_xaxes(title_text='TENOR (YEARS)')
    fig_shocked.update_yaxes(title_text='ZERO RATE (%)')
    st.plotly_chart(fig_shocked, use_container_width=True)

# ─────────────────────────────────────────────────────────────
# V2 PAGES
# ─────────────────────────────────────────────────────────────
elif page == "Executive Risk Dashboard":
    res = run_v2_engines()
    st.markdown("# Executive Risk Dashboard")
    export_strip()

    if not res['portfolio_exposure']:
        st.markdown("<div class='stAlert'>PORTFOLIO EMPTY — ADD TRADES VIA TRADE CAPTURE MODULE</div>",
                    unsafe_allow_html=True)
    else:
        total_mtm = sum(res['current_mtms'].values())
        total_ee  = res['portfolio_exposure']['EE']
        total_pfe = res['portfolio_exposure']['PFE']

        section_header("PORTFOLIO KPIs")
        cols = st.columns(4)
        cols[0].metric("TOTAL PORTFOLIO MTM",    f"₹{total_mtm:.2f} CR", accent="blue")
        cols[1].metric("MAX EXPECTED EXPOSURE",  f"₹{np.max(total_ee):.2f} CR", accent="amber")
        cols[2].metric("MAX PFE 95%",            f"₹{np.max(total_pfe):.2f} CR", accent="red")
        cols[3].metric("ACTIVE TRADES",          str(len(res['trades'])), accent="green")

        section_header("NETTED PORTFOLIO EXPOSURE PROFILE")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=res['time_grid'], y=total_ee, name='EE', mode='lines',
                                  line=dict(color=COLORS['EE'], width=2.5),
                                  fill='tozeroy', fillcolor='rgba(0,170,255,0.06)',
                                  hovertemplate='<b>EE:</b> ₹%{y:.4f} Cr<extra></extra>'))
        fig.add_trace(go.Scatter(x=res['time_grid'], y=total_pfe, name='PFE 95%', mode='lines',
                                  line=dict(color=COLORS['PFE'], width=2),
                                  hovertemplate='<b>PFE 95%:</b> ₹%{y:.4f} Cr<extra></extra>'))
        _apply_bbg_chart(fig, 'NETTED PORTFOLIO EXPOSURE (₹ CR)')
        fig.update_layout(hovermode='x unified')
        fig.update_xaxes(title_text='YEARS')
        fig.update_yaxes(title_text='EXPOSURE (₹ CR)')
        st.plotly_chart(fig, use_container_width=True)

elif page == "Trade Capture & Lifecycle":
    res = run_v2_engines()
    st.markdown("# Trade Capture & Lifecycle")
    export_strip()

    section_header("CURRENT TRADE BOOK")
    st.dataframe(res['portfolio_df'], use_container_width=True)

    section_header("ADD NEW TRADE")
    with st.form("add_trade_form"):
        col1, col2, col3 = st.columns(3)
        trade_type = col1.selectbox("TRADE TYPE", ["IRS", "OIS"])
        cpty       = col2.selectbox("COUNTERPARTY", res['cptys_df']['Counterparty'].tolist())
        csa        = col3.selectbox("CSA ID", ["CSA_HDFC_01", "CSA_SBI_01", "CSA_KOTAK_01", "CSA_RELIANCE_01", "CSA_NBFC_01"])

        col4, col5, col6, col7 = st.columns(4)
        new_notional   = col4.number_input("NOTIONAL (₹ CR)", 10.0, 10000.0, 500.0)
        start_date     = col5.date_input("START DATE")
        new_maturity   = col6.number_input("MATURITY (Y)", 1.0, 30.0, 5.0)
        new_fixed_rate = col7.number_input("FIXED RATE (%)", 1.0, 15.0, 7.0)
        new_direction  = st.selectbox("DIRECTION", ["Receive Fixed", "Pay Fixed"])

        if st.form_submit_button("ADD TRADE"):
            PortfolioManager.add_trade({
                'TradeType': trade_type, 'Counterparty': cpty,
                'Notional': new_notional, 'StartDate': start_date.strftime("%Y-%m-%d"),
                'Maturity': new_maturity, 'FixedRate': new_fixed_rate,
                'Direction': new_direction, 'CSA_ID': csa
            })
            run_v2_engines.clear()
            st.success("TRADE ADDED — RECALCULATING...")

elif page == "Pre-Trade XVA Impact":
    st.markdown("# Pre-Trade XVA Impact")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "MARGINAL XVA IMPACT ASSESSMENT — IDENTICAL-PATH MONTE CARLO</div>",
                unsafe_allow_html=True)

    section_header("PROPOSED TRADE PARAMETERS")
    cptys = PortfolioManager.load_counterparties()['Counterparty'].tolist()

    with st.form("pretrade_form"):
        col1, col2, col3 = st.columns(3)
        pt_cpty      = col1.selectbox("COUNTERPARTY", cptys)
        pt_csa       = col2.selectbox("CSA ID", ["UNCOLLATERALISED", "CSA_HDFC_01", "CSA_SBI_01"])
        pt_direction = col3.selectbox("DIRECTION", ["Receive Fixed", "Pay Fixed"])
        col4, col5   = st.columns(2)
        pt_notional  = col4.number_input("NOTIONAL (₹ CR)", 10.0, 10000.0, 500.0)
        pt_maturity  = col5.number_input("MATURITY (Y)", 1.0, 30.0, 5.0)
        pt_rate      = st.number_input("FIXED RATE (%)", 1.0, 15.0, 7.0)

        if st.form_submit_button("CALCULATE MARGINAL IMPACT"):
            with st.spinner("RUNNING IDENTICAL-PATH MONTE CARLO..."):
                from src.workflow.incremental_xva import IncrementalXVAEngine
                trade = {'TradeID': -1, 'Counterparty': pt_cpty, 'Notional': pt_notional,
                         'FixedRate': pt_rate, 'Maturity': pt_maturity,
                         'Direction': pt_direction, 'CSA_ID': pt_csa}
                eng = IncrementalXVAEngine()
                rep = eng.impact_report(trade)
                section_header("MARGINAL IMPACT REPORT")
                st.dataframe(rep, use_container_width=True)

elif page == "Capital & RAROC Analytics":
    res = run_v2_engines()
    st.markdown("# Capital & RAROC Analytics")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "RISK-ADJUSTED RETURN ON CAPITAL — HURDLE RATE: 10.0%</div>",
                unsafe_allow_html=True)
    export_strip()

    section_header("TRADE RAROC EVALUATION", "Risk-Adjusted Return on Capital per trade — EVA = RAROC vs Hurdle rate")
    df = res['ranked_df']
    if not df.empty:
        from src.raroc.raroc_engine import RAROCEngine
        eng        = RAROCEngine(hurdle_rate=0.10)
        raroc_data = []
        for _, row in df.iterrows():
            rev  = row.get('Revenue', row['EAD'] * 0.05)
            el   = row['EAD'] * 0.01
            # ranked_df now carries genuine per-trade CVA / FVA / KVA
            cva  = row.get('CVA', 0.0)
            fva  = row.get('FVA', 0.0)
            kva  = row.get('KVA', 0.0)
            xva  = cva + fva + kva
            cap  = row['Capital']
            r_r  = eng.compute_raroc(rev, el, rev * 0.1, xva, cap)
            raroc_data.append({
                'TradeID':     row['TradeID'],
                'Counterparty': row.get('Counterparty', 'N/A'),
                'Revenue':      rev,
                'Exp Loss':     el,
                'XVA':          xva,
                'Capital':      cap,
                'RAROC':        r_r['RAROC'],
                'EVA':          r_r['Economic_Value_Added'],
                'Accretive':    r_r['Is_Accretive'],
            })

        raroc_df = pd.DataFrame(raroc_data)

        def _raroc_table(df_r):
            rows = ""
            for _, r in df_r.iterrows():
                rc  = "num-pos" if r['RAROC'] >= 0.10 else "num-neg"
                evc = "num-pos" if r['EVA'] >= 0 else "num-neg"
                acc = "status-pass" if r['Accretive'] else "status-fail"
                rows += f"""<tr>
                  <td>{r['TradeID']}</td>
                  <td>{r['Counterparty']}</td>
                  <td>₹{r['Revenue']:.2f}</td>
                  <td>₹{r['Exp Loss']:.2f}</td>
                  <td>₹{r['XVA']:.2f}</td>
                  <td>₹{r['Capital']:.2f}</td>
                  <td class="{rc}">{r['RAROC']:.2%}</td>
                  <td class="{evc}">₹{r['EVA']:.2f}</td>
                  <td class="{acc}">{"YES" if r['Accretive'] else "NO"}</td>
                </tr>"""
            return (f'<div class="bbg-table-wrap"><table class="bbg-table"><thead><tr>'
                    f'<th>TRADE</th><th>CPTY</th><th>REVENUE</th><th>EL</th>'
                    f'<th>XVA</th><th>CAPITAL</th><th>RAROC</th><th>EVA</th><th>ACCRETIVE</th>'
                    f'</tr></thead><tbody>{rows}</tbody></table></div>')

        st.markdown(_raroc_table(raroc_df), unsafe_allow_html=True)

        raroc_bar_colors = [COLORS['success'] if r >= 0.10 else COLORS['danger_bright']
                            for r in raroc_df['RAROC']]
        fig_raroc = go.Figure()
        fig_raroc.add_trace(go.Bar(
            x=raroc_df['TradeID'].astype(str), y=raroc_df['RAROC'] * 100,
            marker=dict(color=raroc_bar_colors),
            text=[f"{r:.1%}" for r in raroc_df['RAROC']],
            textposition='outside',
            textfont=dict(family=_MONO, color='#e0e0e0', size=9),
            hovertemplate='<b>Trade %{x}</b><br>RAROC: %{y:.2f}%<extra></extra>'
        ))
        fig_raroc.add_hline(y=10.0, line_dash='dash', line_color=COLORS['EPE'],
                             annotation_text='HURDLE 10%',
                             annotation_font=dict(color=COLORS['EPE'], size=9))
        _apply_bbg_chart(fig_raroc, 'TRADE RAROC VS HURDLE RATE')
        fig_raroc.update_xaxes(title_text='TRADE ID')
        fig_raroc.update_yaxes(title_text='RAROC (%)')
        st.plotly_chart(fig_raroc, use_container_width=True)
    else:
        st.markdown("<div class='stAlert'>NO TRADES IN PORTFOLIO — ADD TRADES VIA TRADE CAPTURE</div>",
                    unsafe_allow_html=True)

elif page == "Data & Infrastructure Monitor":
    st.markdown("# Data & Infrastructure Monitor")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "EOD RISK SNAPSHOT STORE — SQLITE — TRADE/COUNTERPARTY/CSA MASTER DATA</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.data_ingestion.portfolio_manager import PortfolioManager
    port_df = PortfolioManager.load_portfolio()
    cpty_df = PortfolioManager.load_counterparties()
    csa_df  = PortfolioManager.load_csas()

    section_header("DATABASE LAYER STATUS")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ACTIVE TRADES",    str(len(port_df)),   accent="green")
    col2.metric("COUNTERPARTIES",   str(len(cpty_df)),   accent="blue")
    col3.metric("CSA AGREEMENTS",   str(len(csa_df)),    accent="amber")
    col4.metric("DB ENGINE",        "SQLITE",            accent="blue")

    section_header("TRADE BOOK")
    st.dataframe(port_df, use_container_width=True)

    section_header("COUNTERPARTY MASTER")
    st.dataframe(cpty_df, use_container_width=True)

    # ── FIMMDA Corporate Bond Z-Spreads (Gap 7) ──────────────────────────
    section_header("FIMMDA CORPORATE BOND Z-SPREADS",
                   "Live FIMMDA daily valuation sheet with fallback to published sector-average spreads")
    try:
        with st.spinner("FETCHING FIMMDA BOND Z-SPREADS..."):
            zspreads = cached_fimmda_zspread()
    except Exception as _e:
        zspreads = {}
        st.markdown(f"<div class='stAlert'>FIMMDA FETCH UNAVAILABLE — {str(_e)[:60]}</div>",
                    unsafe_allow_html=True)

    if zspreads:
        zrows = ""
        for issuer, spread in sorted(zspreads.items(), key=lambda kv: kv[1]):
            cls = "num-pos" if spread < 50 else "num-warn" if spread < 120 else "num-neg"
            zrows += f"<tr><td>{issuer}</td><td class='{cls}'>{spread:.1f}</td></tr>"
        st.markdown(f"<div class='bbg-table-wrap'><table class='bbg-table'><thead><tr>"
                    f"<th>ISSUER / SECTOR</th><th>Z-SPREAD (BPS)</th></tr></thead>"
                    f"<tbody>{zrows}</tbody></table></div>", unsafe_allow_html=True)

        zfig = go.Figure()
        zn = list(zspreads.keys())
        zv = list(zspreads.values())
        zcolors = [COLORS['success'] if v < 50 else COLORS['EPE'] if v < 120 else COLORS['danger_bright']
                   for v in zv]
        zfig.add_trace(go.Bar(x=zn, y=zv, marker=dict(color=zcolors),
                              hovertemplate='<b>%{x}</b><br>Z-spread: %{y:.0f} bps<extra></extra>'))
        _apply_bbg_chart(zfig, 'FIMMDA BOND Z-SPREADS BY ISSUER / SECTOR')
        zfig.update_yaxes(title_text='Z-SPREAD (BPS)')
        st.plotly_chart(zfig, use_container_width=True)


elif page == "Bilateral Valuation Analytics":
    res = run_v2_engines()
    st.title("Bilateral Valuation (First-to-Default CVA/DVA)")
    st.markdown("True BCVA incorporating joint survival probability.")
    
    cpty = st.selectbox("Select Counterparty", res['cptys_df']['Counterparty'].tolist())
    own_cds = st.number_input("Bank Own CDS Spread (bps)", 10.0, 1000.0, 40.0)
    
    if st.button("Run Bilateral Analytics"):
        with st.spinner("Computing First-to-Default BCVA & DVA01..."):
            from src.workflow.bilateral import BilateralValuationEngine
            from src.xva.cva import CreditCurve
            
            cpty_row = res['cptys_df'][res['cptys_df']['Counterparty'] == cpty].iloc[0]
            cpty_cds = float(cpty_row['CDS_Spread_BPS'])
            cpty_curve = CreditCurve(cpty_cds)
            own_curve = CreditCurve(own_cds)
            
            # Reconstruct exposure profile for selected cpty
            from src.workflow.portfolio_xva import PortfolioXVAContext
            ctx = PortfolioXVAContext(n_paths=500)
            trades = [t for t in PortfolioManager.load_portfolio().to_dict('records') 
                      if t['Counterparty'] == cpty]
            
            # To get EE/ENE, we can extract from the context
            netting = NettingEngine(ctx.time_grid, ctx.rate_paths, ctx.hw_model)
            trade_paths = netting.calculate_trade_mtm_paths(trades, projection_curve=ctx.mcf.mibor)
            csa_mtm = netting.aggregate_by_csa(trades, trade_paths=trade_paths)
            csa_exposures = netting.apply_collateral(csa_mtm)
            
            ee = np.zeros_like(ctx.time_grid)
            ene = np.zeros_like(ctx.time_grid)
            for metrics in csa_exposures.values():
                ee += metrics['EE']
                ene += metrics.get('ENE', np.zeros_like(ee))
            
            eng = BilateralValuationEngine(ctx.ois_curve)
            report = eng.full_bilateral_report(ee, ene, ctx.time_grid, cpty_curve, own_curve)
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("FIRST-TO-DEFAULT CVA", f"₹{report['CVA_FTD']:.4f} CR", accent="red")
            col2.metric("FIRST-TO-DEFAULT DVA", f"₹{report['DVA_FTD']:.4f} CR", accent="green")
            col3.metric("TRUE BCVA", f"₹{report['BCVA_FTD']:.4f} CR", accent="amber")
            col4.metric("DVA01 (BANK SPREAD)", f"₹{report['DVA01']:.6f} CR", accent="blue")

elif page == "Counterparty Limit Monitor":
    st.markdown("# Counterparty Limit Monitor")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "REAL-TIME EXPOSURE MONITORING AGAINST LEGAL ENTITY LIMITS</div>",
                unsafe_allow_html=True)
    export_strip()

    sample_limits = [
        {'LegalEntityID': 'LE_HDFC',  'Metric': 'EAD',    'LimitAmount': 350.0},
        {'LegalEntityID': 'LE_HDFC',  'Metric': 'PFE_95', 'LimitAmount': 100.0},
        {'LegalEntityID': 'LE_SBI',   'Metric': 'EAD',    'LimitAmount': 600.0},
        {'LegalEntityID': 'LE_SBI',   'Metric': 'PFE_95', 'LimitAmount': 200.0},
        {'LegalEntityID': 'LE_KOTAK', 'Metric': 'EAD',    'LimitAmount': 150.0},
        {'LegalEntityID': 'LE_KOTAK', 'Metric': 'PFE_95', 'LimitAmount': 50.0},
    ]

    if st.button("REFRESH LIMITS & EXPOSURES"):
        with st.spinner("AGGREGATING EXPOSURES BY LEGAL ENTITY..."):
            from src.limits.limit_engine import LimitEngine
            from src.workflow.hierarchy import HierarchyManager

            res       = run_v2_engines()
            entities  = [{'EntityID': f"LE_{c}", 'EntityName': f"{c} Entity"}
                         for c in res['cptys_df']['Counterparty']]
            hm        = HierarchyManager(entities, [])
            grouped   = hm.aggregate_by_legal_entity(PortfolioManager.load_portfolio().to_dict('records'))

            actuals = {}
            for le, le_trades in grouped.items():
                cpty_name = le_trades[0]['Counterparty']
                c_data    = res.get('cpty_results', {}).get(cpty_name, {})
                actuals[le] = {
                    'EAD':    c_data.get('EAD', 0.0),
                    'PFE_95': float(c_data.get('PFE_profile', [0])[-1]) if 'PFE_profile' in c_data else c_data.get('EPE', 0) * 2
                }

            eng       = LimitEngine(sample_limits)
            status_df = eng.check_limits(actuals)

            if not status_df.empty:
                def _status_cls(v):
                    return 'status-pass' if v == 'GREEN' else 'status-warn' if v == 'AMBER' else 'status-fail'
                rows = ""
                for _, r in status_df.iterrows():
                    sc = _status_cls(r.get('Status', ''))
                    rows += f"<tr>{''.join(f'<td class={sc if c==status_df.columns.get_loc(col) else chr(0)}>{str(r[col])}</td>' for c, col in enumerate(status_df.columns))}</tr>"
                st.dataframe(status_df, use_container_width=True)

elif page == "XVA Explain & Attribution":
    st.markdown("# XVA Explain & Attribution")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "DAILY CVA ATTRIBUTION — FIRST-ORDER TAYLOR DECOMPOSITION</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.xva.attribution import XVAAttribution

    section_header("ATTRIBUTION INPUTS")
    col1, col2 = st.columns(2)
    cva_yesterday = col1.number_input("CVA YESTERDAY (₹ CR)", value=4.20, step=0.1)
    cva_today     = col2.number_input("CVA TODAY (₹ CR)",     value=4.65, step=0.1)
    spread_move   = col1.number_input("CDS SPREAD MOVE (BPS)", value=8.0, step=1.0)
    exposure_chg  = col2.number_input("EXPOSURE CHANGE (%)", value=2.5, step=0.5) / 100.0

    attribution = XVAAttribution.explain_cva_change(
        cva_yesterday=cva_yesterday, cva_today=cva_today,
        spread_move_bps=spread_move, exposure_change_pct=exposure_chg,
    )

    section_header("ATTRIBUTION BREAKDOWN")
    cols   = st.columns(5)
    labels = ['Total Change', 'Spread Move', 'Exposure Move', 'Time Decay', 'Unexplained']
    accents = ['blue', 'amber', 'amber', 'green', 'red']
    for col, label, acc in zip(cols, labels, accents):
        val = attribution[label]
        col.metric(label.upper(), f"₹{val:+.3f} CR", accent=acc)

    fig_attr = go.Figure(go.Waterfall(
        name="CVA ATTRIBUTION", orientation="v",
        measure=["relative", "relative", "relative", "relative", "total"],
        x=["SPREAD MOVE", "EXPOSURE MOVE", "TIME DECAY", "UNEXPLAINED", "TOTAL CHANGE"],
        y=[attribution["Spread Move"], attribution["Exposure Move"],
           attribution["Time Decay"], attribution["Unexplained"],
           attribution["Total Change"]],
        text=[f"₹{v:+.3f}" for v in [attribution["Spread Move"], attribution["Exposure Move"],
              attribution["Time Decay"], attribution["Unexplained"], attribution["Total Change"]]],
        textposition='outside',
        textfont=dict(family=_MONO, color='#e0e0e0', size=9),
        connector={"line": {"color": "#243040"}},
        increasing={"marker": {"color": COLORS['success']}},
        decreasing={"marker": {"color": COLORS['danger_bright']}},
        totals={"marker": {"color": COLORS['EE']}},
        hovertemplate='<b>%{x}</b><br>₹%{y:+.4f} Cr<extra></extra>'
    ))
    _apply_bbg_chart(fig_attr, 'CVA WATERFALL ATTRIBUTION')
    st.plotly_chart(fig_attr, use_container_width=True)

elif page == "Volatility & Optionality Analytics":
    st.markdown("# Volatility & Optionality Analytics")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "EUROPEAN SWAPTION — BACHELIER (NORMAL) MODEL — INR MARKET STANDARD</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.pricing.swaption import EuropeanSwaption

    ois_data, _, _, _, _ = load_market_data()
    ois_curve_sw = OISCurve(ois_data['tenor_years'].values, ois_data['ois_rate'].values)

    col1, col2, col3 = st.columns(3)
    sw_notional = col1.number_input("NOTIONAL (₹ CR)", value=500.0, step=50.0)
    sw_expiry   = col2.slider("OPTION EXPIRY (YRS)", 1, 5, 2)
    sw_tenor    = col3.slider("SWAP TENOR (YRS)", 1, 10, 5)
    sw_strike   = col1.number_input("STRIKE RATE (%)", value=7.0, step=0.1) / 100.0
    sw_vol      = col2.number_input("NORMAL VOL (BPS)", value=55.0, step=5.0) / 10000.0
    sw_type     = col3.selectbox("OPTION TYPE", ["Payer", "Receiver"])

    pricer_underlying = SwapPricer(notional=sw_notional, fixed_rate=sw_strike,
                                    maturity=float(sw_expiry + sw_tenor), direction="Receive Fixed")
    fwd_rate = pricer_underlying.par_rate(ois_curve_sw)
    annuity  = pricer_underlying.annuity(ois_curve_sw)

    sw = EuropeanSwaption(notional=sw_notional, strike=sw_strike,
                           maturity=float(sw_expiry), swap_tenor=float(sw_tenor))

    if sw_type == "Receiver":
        from scipy.stats import norm
        d   = (sw.strike - fwd_rate) / (sw_vol * np.sqrt(sw.maturity))
        pv  = annuity * ((sw.strike - fwd_rate) * norm.cdf(d) + sw_vol * np.sqrt(sw.maturity) * norm.pdf(d))
        swaption_pv = pv * sw_notional
    else:
        swaption_pv = sw.price_bachelier(fwd_rate, sw_vol, annuity)

    sw_vol_up = sw_vol + 0.0001
    vega      = (sw.price_bachelier(fwd_rate, sw_vol_up, annuity) - swaption_pv) * sw_notional

    section_header("SWAPTION PRICING RESULTS")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("FORWARD SWAP RATE", f"{fwd_rate*100:.3f}%", accent="blue")
    col2.metric("ANNUITY FACTOR",    f"{annuity:.4f}",       accent="amber")
    col3.metric(f"{sw_type.upper()} SWAPTION PV", f"₹{swaption_pv:.4f} CR", accent="green")
    col4.metric("VEGA (₹ CR / 1BP VOL)", f"{vega:.4f}",      accent="amber")

# ─────────────────────────────────────────────────────────────
# PAGE: V4 Enhancements
# ─────────────────────────────────────────────────────────────
elif page == "Rates & Volatility Analytics":
    st.markdown("# Rates & Volatility Analytics")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "MULTI-CURVE FRAMEWORK — OIS DISCOUNTING + MIBOR FORWARD — NORMAL SABR VOL SURFACE</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.curves.multi_curve import MultiCurveFramework
    from src.pricing.sabr import VolSurface
    from src.pricing.swaption import EuropeanSwaption, price_swaption_sabr
    from src.data_ingestion.market_data import get_ois_market_data

    ois_data    = get_ois_market_data()
    multi_curve = MultiCurveFramework.build_from_market_data()
    vol_surface = VolSurface.build_from_market_data()

    section_header("MULTI-CURVE BOOTSTRAPPING", "OIS for discounting, MIBOR for forward rate projection — dual-curve framework")
    st.metric("OIS-MIBOR BASIS SPREAD", f"{multi_curve.basis_bps:.2f} BPS", accent="amber")

    t_grid    = np.linspace(0.1, 10.0, 100)
    ois_fwd   = [multi_curve.discount.df(t) for t in t_grid]
    mibor_fwd = [multi_curve.mibor.df(t) for t in t_grid]

    fig_mc = go.Figure()
    fig_mc.add_trace(go.Scatter(x=t_grid, y=ois_fwd, name="OIS DISCOUNT FACTORS", mode='lines',
                                 line=dict(color=COLORS['success'], width=2.5),
                                 hovertemplate='<b>OIS DF:</b> %{y:.6f}<extra></extra>'))
    fig_mc.add_trace(go.Scatter(x=t_grid, y=mibor_fwd, name="MIBOR DISCOUNT FACTORS", mode='lines',
                                 line=dict(color=COLORS['EE'], width=2, dash='dash'),
                                 hovertemplate='<b>MIBOR DF:</b> %{y:.6f}<extra></extra>'))
    _apply_bbg_chart(fig_mc, 'OIS VS MIBOR DISCOUNT FACTORS')
    fig_mc.update_xaxes(title_text='TENOR (YEARS)')
    fig_mc.update_yaxes(title_text='DISCOUNT FACTOR')
    st.plotly_chart(fig_mc, use_container_width=True)

    section_header("SABR SWAPTION PRICING")
    col1, col2, col3 = st.columns(3)
    sw_expiry = col1.slider("SABR EXPIRY (Y)", 1.0, 10.0, 5.0, key="sabr_exp")
    sw_tenor  = col2.slider("SABR TENOR (Y)",  1.0, 10.0, 5.0, key="sabr_ten")
    sw_strike = col3.number_input("SABR STRIKE (%)", value=7.0, step=0.1, key="sabr_stk") / 100.0

    pricer = EuropeanSwaption(notional=notional, strike=sw_strike, maturity=sw_expiry, swap_tenor=sw_tenor)
    
    # Extract fwd rate and annuity dynamically from the dual-curve
    annuity = sum([multi_curve.discount.df(sw_expiry + i) for i in range(1, int(sw_tenor)+1)])
    fwd_rate = (multi_curve.discount.df(sw_expiry) - multi_curve.discount.df(sw_expiry + sw_tenor)) / annuity
    
    sabr_pv = price_swaption_sabr(pricer, fwd_rate, annuity, vol_surface)
    c1s, c2s, c3s = st.columns(3)
    c1s.metric("SABR SWAPTION PV (₹ CR)", f"₹{sabr_pv:.4f}", accent="green")
    c2s.metric("FORWARD RATE", f"{fwd_rate*100:.4f}%", accent="blue")
    c3s.metric("ANNUITY", f"{annuity:.4f}", accent="amber")

    section_header("SABR ATM VOLATILITY SURFACE")
    vol_df = vol_surface.to_dataframe()
    vol_pivot = vol_df.pivot(index='expiry_years', columns='tenor_years', values='atm_normal_vol_bps')
    
    fig_vol = go.Figure(data=[go.Surface(
        z=vol_pivot.values, x=vol_pivot.columns, y=vol_pivot.index,
        colorscale=[[0, '#0d1117'], [0.25, '#003366'], [0.5, '#ff6600'], [0.75, '#ffaa00'], [1, '#ffffff']],
        showscale=True
    )])
    fig_vol.update_layout(
        title="ATM NORMAL VOLATILITY (BPS)",
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='#0d1117',
        font=dict(family=_MONO, color='#e0e0e0', size=9),
        scene=dict(
            xaxis=dict(title='TENOR (Y)', gridcolor='#243040', color='#8899aa'),
            yaxis=dict(title='EXPIRY (Y)', gridcolor='#243040', color='#8899aa'),
            zaxis=dict(title='VOL (BPS)',  gridcolor='#243040', color='#8899aa'),
            bgcolor='#0d1117',
        ),
        margin=dict(l=0, r=0, b=0, t=40)
    )

    strikes    = np.linspace(0.04, 0.10, 50)
    smile_vols = [vol_surface.implied_vol(sw_expiry, sw_tenor, fwd_rate, k) * 10000 for k in strikes]
    fig_smile  = go.Figure(go.Scatter(
        x=strikes * 100, y=smile_vols, mode='lines',
        line=dict(color=COLORS['accent'], width=2.5),
        hovertemplate='<b>Strike:</b> %{x:.2f}%<br><b>Vol:</b> %{y:.1f} bps<extra></extra>'
    ))
    _apply_bbg_chart(fig_smile, f'SABR VOL SMILE — EXPIRY={sw_expiry}Y TENOR={sw_tenor}Y')
    fig_smile.update_xaxes(title_text='STRIKE (%)')
    fig_smile.update_yaxes(title_text='NORMAL IMPLIED VOL (BPS)')

    col_v1, col_v2 = st.columns(2)
    with col_v1:
        st.plotly_chart(fig_vol, use_container_width=True)
    with col_v2:
        st.plotly_chart(fig_smile, use_container_width=True)

elif page == "Collateral & Margin Analytics":
    st.markdown("# Collateral & Margin Analytics")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "PARQUET EXPOSURE CUBE — PATHWISE FVA v2 — SIMM MVA</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.exposure.exposure_cube import ExposureCube
    from src.xva.fva_v2 import FVAEngineV2
    from src.xva.simm import MVAEngineV2

    cube_path = "data/exposure_cube.parquet"

    if st.button("GENERATE CUBE FROM ACTIVE TRADE"):
        cube = ExposureCube(cube_path)
        cube.write_paths("TRADE_CURRENT", time_grid, mtm_paths)
        cube.flush()
        st.success("CUBE GENERATED — ACTIVE TRADE SIMULATION PERSISTED")

    if os.path.exists(cube_path):
        cube      = ExposureCube(cube_path)
        cube_tids = cube.get_summary().get('trade_list', [])
        st.markdown(f"<div style='color:#8899aa;font-size:0.72rem'>CUBE ACTIVE — TRADES: "
                    f"<span style='color:#ff6600'>{cube_tids}</span></div>", unsafe_allow_html=True)

        if cube_tids:
            df_trade  = cube.read_trade(cube_tids[0])
            tg_cube   = np.sort(df_trade['time_step'].unique())
            npv_paths = df_trade.pivot(index='path_id', columns='time_step', values='npv').values

            section_header("MONTE CARLO NPV PATHS")
            fig_cube = go.Figure()
            for i in range(min(50, npv_paths.shape[0])):
                fig_cube.add_trace(go.Scatter(x=tg_cube, y=npv_paths[i, :], mode='lines',
                                               line=dict(color=COLORS['EE'], width=0.6),
                                               opacity=0.25, showlegend=False))
            _apply_bbg_chart(fig_cube, 'MONTE CARLO NPV PATHS (FIRST 50)')
            fig_cube.update_xaxes(title_text='YEARS')
            fig_cube.update_yaxes(title_text='NPV (₹ CR)')
            st.plotly_chart(fig_cube, use_container_width=True)

            section_header("PATHWISE FVA")
            fva_engine2 = FVAEngineV2()
            dfs_cube    = np.array([ois_curve.df(float(t)) for t in tg_cube])
            fva_res     = fva_engine2.compute_fva_pathwise(tg_cube, npv_paths, dfs_cube)
            c1, c2, c3  = st.columns(3)
            c1.metric("FVA (NET)",  f"₹{fva_res['FVA']:.4f} CR", accent="amber")
            c2.metric("FCA (COST)", f"₹{fva_res['FCA']:.4f} CR", accent="red")
            c3.metric("FBA (BENEFIT)", f"₹{fva_res['FBA']:.4f} CR", accent="green")

            section_header("SIMM DYNAMIC IM / MVA")
            mva_engine   = MVAEngineV2(funding_spread=0.015)
            pricer_mva   = SwapPricer(notional=notional, fixed_rate=fixed_rate,
                                       maturity=float(maturity), direction=direction)
            kr_dv01      = pricer_mva.key_rate_dv01(ois_curve)
            tenor_map    = {'1.0': '1Y', '2.0': '2Y', '3.0': '3Y', '5.0': '5Y', '10.0': '10Y'}
            simm_sens    = {tenor_map[k.replace('Y','').strip()]: abs(v) * 10000 * 1e7
                            for k, v in kr_dv01.items() if k.replace('Y','').strip() in tenor_map}
            if not simm_sens:
                simm_sens = {'5Y': abs(pricer_mva.dv01(ois_curve)) * 10000 * 1e7}

            im_profile   = mva_engine.estimate_dim_profile(float(maturity), tg_cube, simm_sens)
            mva          = mva_engine.compute_mva(tg_cube, im_profile, dfs_cube)
            im_t0        = mva_engine.simm.compute_im_rates_delta(simm_sens)

            c1m, c2m = st.columns(2)
            c1m.metric("SIMM IM AT INCEPTION (₹)", f"₹{im_t0:,.0f}", accent="amber")
            c2m.metric("SIMM MVA (₹ CR)",           f"₹{mva:.4f}",    accent="red")
    else:
        st.markdown("<div class='stAlert'>EXPOSURE CUBE NOT FOUND — GENERATE FROM ACTIVE TRADE FIRST</div>",
                    unsafe_allow_html=True)

elif page == "PnL Explain":
    st.markdown("# PnL Explain")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "SWAP PNL ATTRIBUTION — CARRY / ROLL-DOWN / DELTA / GAMMA / NEW FIXING / UNEXPLAINED</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.xva.pnl_attribution import SwapPnLAttribution

    col_left, _ = st.columns([1, 2])
    with col_left:
        pnl_days     = st.slider("DAYS TO SHOW", min_value=2, max_value=10, value=5, key="pnl_days")
        pnl_notional = st.number_input("NOTIONAL (₹ CR)", value=float(notional), step=50.0, key="pnl_notional")
        pnl_rate     = st.number_input("FIXED RATE (%)", value=float(fixed_rate * 100), step=0.05, key="pnl_rate") / 100.0
        pnl_maturity = st.number_input("MATURITY (Y)", value=float(maturity), step=0.5, key="pnl_mat")

    daily_curves  = SwapPnLAttribution.build_daily_curve_sequence(n_days=pnl_days + 1)
    attr          = SwapPnLAttribution(notional=pnl_notional, fixed_rate=pnl_rate, maturity_years=pnl_maturity)
    daily_results = []
    for i in range(1, len(daily_curves)):
        result_df = attr.full_attribution(daily_curves[i], daily_curves[i - 1])
        row       = dict(zip(result_df['Effect'], result_df['PnL (₹ Cr)']))
        row['Day'] = f"DAY {i}"
        daily_results.append(row)

    latest    = daily_results[-1]
    total_val = latest.get('TOTAL', 0.0)
    effects   = ['Carry', 'Roll-Down', 'Delta', 'Gamma', 'New Fixing', 'Unexplained']

    section_header(f"DAY {pnl_days} PNL ATTRIBUTION")
    cols = st.columns(6)
    pnl_accents = ['green', 'green', 'blue', 'blue', 'amber', 'red']
    for col, key, acc in zip(cols, effects, pnl_accents):
        col.metric(key.upper(), f"₹{latest.get(key, 0.0):.4f} CR", accent=acc)
    st.metric("TOTAL PNL", f"₹{total_val:.4f} CR", accent="blue")

    values   = [latest.get(e, 0.0) for e in effects]
    measures = ['relative'] * len(effects) + ['total']

    fig_pnl = go.Figure(go.Waterfall(
        name="PNL ATTRIBUTION", orientation="v",
        measure=measures,
        x=[e.upper() for e in effects] + ['TOTAL PNL'],
        y=values + [total_val],
        text=[f"₹{v:+.4f}" for v in values + [total_val]],
        textposition='outside',
        textfont=dict(family=_MONO, color='#e0e0e0', size=9),
        connector={"line": {"color": "#243040"}},
        increasing={"marker": {"color": COLORS['success']}},
        decreasing={"marker": {"color": COLORS['danger_bright']}},
        totals={"marker": {"color": COLORS['EE']}},
        hovertemplate='<b>%{x}</b><br>₹%{y:+.4f} Cr<extra></extra>'
    ))
    _apply_bbg_chart(fig_pnl, f'PNL WATERFALL — DAY {pnl_days}  ({total_val:+.4f} ₹ CR)')
    st.plotly_chart(fig_pnl, use_container_width=True)

    section_header("DAILY ATTRIBUTION STACK")
    pnl_colors = {'Carry': COLORS['success'], 'Roll-Down': '#66cc44',
                  'Delta': COLORS['EE'], 'Gamma': '#8855ff',
                  'New Fixing': COLORS['EPE'], 'Unexplained': COLORS['dim']}
    fig_multi = go.Figure()
    for effect in effects:
        fig_multi.add_trace(go.Bar(
            name=effect.upper(),
            x=[r['Day'] for r in daily_results],
            y=[r.get(effect, 0.0) for r in daily_results],
            marker_color=pnl_colors.get(effect, '#556677'),
            hovertemplate=f'<b>{effect}</b><br>₹%{{y:+.4f}} Cr<extra></extra>'
        ))
    _apply_bbg_chart(fig_multi, 'DAILY PNL ATTRIBUTION STACK')
    fig_multi.update_layout(barmode='relative')
    fig_multi.update_xaxes(title_text='DAY')
    fig_multi.update_yaxes(title_text='₹ CR')
    st.plotly_chart(fig_multi, use_container_width=True)

    section_header("FULL ATTRIBUTION TABLE")
    daily_df = pd.DataFrame(daily_results).set_index('Day')
    st.dataframe(daily_df[['Carry', 'Roll-Down', 'Delta', 'Gamma',
                             'New Fixing', 'Unexplained', 'TOTAL']].round(6),
                 use_container_width=True)

elif page == "Model Risk & Validation":
    st.markdown("# Model Risk & Validation")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "MRM QUANTITATIVE MODEL VALIDATION SUITE</div>", unsafe_allow_html=True)
    export_strip()

    from src.validation.model_validator import ModelValidationSuite

    if st.button("RUN FULL VALIDATION SUITE"):
        with st.spinner("EXECUTING MRM VALIDATION..."):
            suite     = ModelValidationSuite()
            report_df = suite.run_all()
            passes    = len(report_df[report_df['Status'] == 'PASS'])
            total     = len(report_df)

            section_header("VALIDATION RESULTS")
            c1, c2, c3 = st.columns(3)
            c1.metric("PASSED",  str(passes),          accent="green")
            c2.metric("FAILED",  str(total - passes),   accent="red")
            c3.metric("SCORE",   f"{passes}/{total}",   accent="blue")

            def _val_table(df):
                rows = ""
                for _, r in df.iterrows():
                    sc = 'status-pass' if r['Status'] == 'PASS' else 'status-fail' if r['Status'] == 'FAIL' else 'status-warn'
                    dot = f'<span class="status-dot {"green" if r["Status"]=="PASS" else "red" if r["Status"]=="FAIL" else "amber"}"></span>'
                    rows += f"<tr><td>{r.get('Test','')}</td><td class='{sc}'>{dot}{r['Status']}</td>"
                    for col in df.columns[2:]:
                        rows += f"<td>{r[col]}</td>"
                    rows += "</tr>"
                hdrs = "".join(f"<th>{c.upper()}</th>" for c in df.columns)
                return (f'<div class="bbg-table-wrap"><table class="bbg-table">'
                        f'<thead><tr>{hdrs}</tr></thead><tbody>{rows}</tbody></table></div>')

            st.markdown(_val_table(report_df), unsafe_allow_html=True)

    # ── Vectorised engine benchmark (Gap 8) ──────────────────────────────
    section_header("VECTORISED ENGINE BENCHMARK", "Validates the NumPy-vectorised CVA against the loop-based engine and times both")
    if st.button("RUN VECTORISED BENCHMARK"):
        import time as _time
        from src.utils.vectorised_ops import vectorised_cva
        cc_bm = credit_curve
        dfs_bm = np.array([ois_curve.df(t) for t in time_grid])

        t0 = _time.perf_counter()
        for _ in range(200):
            cva_loop = CVAEngine(ois_curve).compute_cva(metrics['EE'], time_grid, cc_bm)
        t_loop = (_time.perf_counter() - t0) / 200 * 1e3

        t0 = _time.perf_counter()
        for _ in range(200):
            cva_vec = vectorised_cva(metrics['EE'], time_grid, cc_bm.hazard_rate,
                                     1 - cc_bm.recovery_rate, dfs_bm)
        t_vec = (_time.perf_counter() - t0) / 200 * 1e3

        speedup = t_loop / t_vec if t_vec > 0 else 0.0
        rel_err = abs(cva_vec - cva_loop) / (abs(cva_loop) + 1e-12) * 100

        cols = st.columns(4)
        cols[0].metric("LOOP CVA", f"₹{cva_loop:.6f}", accent="amber")
        cols[1].metric("VECTORISED CVA", f"₹{cva_vec:.6f}", accent="blue")
        cols[2].metric("SPEEDUP", f"{speedup:.1f}×", accent="green")
        cols[3].metric("REL ERROR", f"{rel_err:.4f}%", accent="green")
        st.markdown(f"<div style='color:#8899aa;font-size:0.7rem'>"
                    f"Loop: {t_loop:.4f} ms/call &nbsp;|&nbsp; Vectorised: {t_vec:.4f} ms/call "
                    f"&nbsp;|&nbsp; agreement within {rel_err:.4f}%</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# NEW MODULE PAGES (Gaps 1–6, 9, 10)
# ─────────────────────────────────────────────────────────────
elif page == "FRTB-CVA Capital":
    st.markdown("# FRTB-CVA Capital")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "BASEL IV SA-CVA — STANDARDISED APPROACH CVA RISK CAPITAL (BIS d457)</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.sa_ccr.frtb_cva import FRTBCVAEngine

    section_header("CVA SENSITIVITIES BY COUNTERPARTY",
                   "CS01 = ΔCVA per 1bp CDS widening; IR01 = ΔCVA per 1bp rate move. "
                   "Computed on the active trade's EE profile against each counterparty's credit curve.")
    cva_engine_frtb = CVAEngine(ois_curve)
    ir_bucket = 'short' if maturity < 1 else 'medium' if maturity <= 5 else 'long'
    cs01_map, ir01_map, ratings_map = {}, {}, {}
    for _, row in counterparties.iterrows():
        nm = row['counterparty']
        cc = CreditCurve(row['cds_spread_bps'], row['recovery_rate'])
        cs01_map[nm] = cva_engine_frtb.cs01(metrics['EE'], time_grid, cc)
        ir01_map[nm] = {'short': 0.0, 'medium': 0.0, 'long': 0.0}
        ir01_map[nm][ir_bucket] = cva_engine_frtb.ir01(metrics['EE'], time_grid, cc)
        ratings_map[nm] = row['rating']

    frtb = FRTBCVAEngine()
    res = frtb.compute_sa_cva_capital(cs01_map, ratings_map, ir01_map)

    cols = st.columns(4)
    cols[0].metric("K_CS DELTA", f"₹{res['K_CS_delta']:.4f} CR", accent="amber")
    cols[1].metric("K_IR DELTA", f"₹{res['K_IR_delta']:.4f} CR", accent="blue")
    cols[2].metric("K TOTAL", f"₹{res['K_total_FRTB_CVA']:.4f} CR", accent="amber")
    cols[3].metric("FRTB-CVA CAPITAL", f"₹{res['FRTB_CVA_Capital_CR']:.4f} CR", accent="red")

    section_header("WEIGHTED CREDIT SPREAD SENSITIVITY BREAKDOWN")
    rows_html = ""
    for nm in cs01_map:
        rows_html += (f"<tr><td>{nm}</td><td>{ratings_map[nm]}</td>"
                      f"<td>{res['RW_'+nm]:.1f}</td>"
                      f"<td>{cs01_map[nm]:.6f}</td>"
                      f"<td class='num-warn'>{res['WS_'+nm]:.6f}</td></tr>")
    st.markdown(f"<div class='bbg-table-wrap'><table class='bbg-table'><thead><tr>"
                f"<th>COUNTERPARTY</th><th>RATING</th><th>CS RW (BPS)</th>"
                f"<th>CS01 (₹CR/BP)</th><th>WEIGHTED SENS</th>"
                f"</tr></thead><tbody>{rows_html}</tbody></table></div>", unsafe_allow_html=True)

    names = list(cs01_map.keys())
    ws_vals = [res['WS_' + nm] for nm in names]
    fig_frtb = go.Figure()
    fig_frtb.add_trace(go.Bar(
        x=names, y=ws_vals, marker=dict(color=COLORS['EPE']),
        text=[f'{v:.4f}' for v in ws_vals], textposition='outside',
        textfont=dict(family=_MONO, color='#e0e0e0', size=9),
        hovertemplate='<b>%{x}</b><br>RW×CS01: %{y:.6f}<extra></extra>'
    ))
    _apply_bbg_chart(fig_frtb, 'WEIGHTED CREDIT SPREAD SENSITIVITY (RW × CS01)')
    fig_frtb.update_xaxes(title_text='COUNTERPARTY')
    fig_frtb.update_yaxes(title_text='WEIGHTED SENS')
    st.plotly_chart(fig_frtb, use_container_width=True)

    with st.expander("METHODOLOGY & DATA SOURCE"):
        st.markdown(
            "<div style='font-size:0.72rem;color:#8899aa;line-height:1.6'>"
            "SA-CVA decomposes CVA capital into credit-spread delta (K_CS) and "
            "interest-rate delta (K_IR), aggregated as "
            "K_total = √(K_CS² + K_IR² + 2·ρ·K_CS·K_IR) with ρ≈0.01.<br>"
            "Risk weights & correlations: BIS FRTB text (d457, free). "
            "Capital = K_total × 10.5% (RBI Basel III).</div>",
            unsafe_allow_html=True)


elif page == "HW2F Term Structure":
    st.markdown("# HW2F Term Structure")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "HULL-WHITE TWO-FACTOR — CALIBRATED TO RBI DBIE MIBOR & G-SEC</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.montecarlo.hull_white_2f import calibrate_hw2f_from_rbi_dbie

    section_header("HW2F CALIBRATION (RBI DBIE)",
                   "Fast factor a/σ1 from MIBOR AR(1); slow factor b/σ2 from G-Sec residuals; ρ empirical")
    with st.spinner("CALIBRATING HW2F FROM FREE RBI DATA..."):
        hw2f = calibrate_hw2f_from_rbi_dbie(ois_curve)
    cols = st.columns(5)
    cols[0].metric("MEAN REV a", f"{hw2f.a:.4f}", accent="amber")
    cols[1].metric("MEAN REV b", f"{hw2f.b:.4f}", accent="amber")
    cols[2].metric("σ1 SHORT", f"{hw2f.sigma1:.4f}", accent="blue")
    cols[3].metric("σ2 LONG", f"{hw2f.sigma2:.4f}", accent="blue")
    cols[4].metric("CORR ρ", f"{hw2f.rho:.3f}", accent="green")

    n_show2 = int(min(n_paths, 2000))
    sim = hw2f.simulate(n_paths=n_show2, n_steps=60, horizon=float(maturity), seed=42)

    col1, col2 = st.columns(2)
    with col1:
        section_header("FACTOR MEANS x(t) / y(t)")
        figx = go.Figure()
        figx.add_trace(go.Scatter(x=sim['time_grid'], y=sim['x_paths'].mean(0) * 100,
                                  name='x — FAST', line=dict(color=COLORS['EE'], width=2.5),
                                  hovertemplate='x: %{y:.4f}%<extra></extra>'))
        figx.add_trace(go.Scatter(x=sim['time_grid'], y=sim['y_paths'].mean(0) * 100,
                                  name='y — SLOW', line=dict(color=COLORS['EPE'], width=2.5),
                                  hovertemplate='y: %{y:.4f}%<extra></extra>'))
        _apply_bbg_chart(figx, 'HW2F FACTOR MEANS (×100)')
        figx.update_xaxes(title_text='TIME (YEARS)')
        figx.update_yaxes(title_text='FACTOR (%)')
        st.plotly_chart(figx, use_container_width=True)
    with col2:
        section_header("SIMULATED SHORT RATE PATHS")
        figr = go.Figure()
        for i in range(min(120, sim['rate_paths'].shape[0])):
            figr.add_trace(go.Scatter(x=sim['time_grid'], y=sim['rate_paths'][i] * 100,
                                      mode='lines', line=dict(color=COLORS['ENE'], width=0.4),
                                      opacity=0.08, showlegend=False))
        figr.add_trace(go.Scatter(x=sim['time_grid'], y=sim['rate_paths'].mean(0) * 100,
                                  name='MEAN RATE', line=dict(color=COLORS['EPE'], width=2.5),
                                  hovertemplate='r: %{y:.4f}%<extra></extra>'))
        _apply_bbg_chart(figr, 'HW2F SHORT RATE PATHS (%)')
        figr.update_xaxes(title_text='TIME (YEARS)')
        figr.update_yaxes(title_text='SHORT RATE (%)')
        st.plotly_chart(figr, use_container_width=True)

    section_header("HW2F vs HW1F EXPOSURE PROFILE",
                   "Two-factor model captures curve twists the single-factor model misses")
    mtm2 = hw2f.compute_swap_mtm_paths(sim['time_grid'], sim['x_paths'], sim['y_paths'],
                                       notional, fixed_rate, float(maturity), direction)
    em2 = hw2f.compute_exposure_metrics(mtm2, sim['time_grid'])
    cc = st.columns(3)
    cc[0].metric("HW2F EPE", f"₹{em2['EPE']:.4f} CR", accent="blue")
    cc[1].metric("HW1F EPE", f"₹{metrics['EPE']:.4f} CR", accent="amber")
    cc[2].metric("HW2F MAX PFE95", f"₹{np.max(em2['PFE']):.4f} CR", accent="red")

    fige = go.Figure()
    fige.add_trace(go.Scatter(x=sim['time_grid'], y=em2['EE'], name='HW2F EE', mode='lines',
                              line=dict(color=COLORS['EE'], width=2.5),
                              hovertemplate='HW2F EE: ₹%{y:.4f} Cr<extra></extra>'))
    fige.add_trace(go.Scatter(x=sim['time_grid'], y=em2['PFE'], name='HW2F PFE95', mode='lines',
                              line=dict(color=COLORS['PFE'], width=2),
                              hovertemplate='HW2F PFE: ₹%{y:.4f} Cr<extra></extra>'))
    fige.add_trace(go.Scatter(x=time_grid, y=metrics['EE'], name='HW1F EE', mode='lines',
                              line=dict(color=COLORS['EPE'], width=1.5, dash='dash'),
                              hovertemplate='HW1F EE: ₹%{y:.4f} Cr<extra></extra>'))
    _apply_bbg_chart(fige, 'EXPOSURE PROFILE: HW2F VS HW1F')
    fige.update_layout(hovermode='x unified')
    fige.update_xaxes(title_text='TIME (YEARS)')
    fige.update_yaxes(title_text='EXPOSURE (₹ CR)')
    st.plotly_chart(fige, use_container_width=True)


elif page == "CVA Greeks & Hedging":
    st.markdown("# CVA Greeks & Hedging")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                f"DAILY CCR DESK RISK PACK — {cpty_selected.upper()} — CS01 / IR01 / GAMMA + CDS HEDGE</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.xva.credit_contingent import CDSHedgeEngine

    cva_eng = CVAEngine(ois_curve)
    own_cc = CreditCurve(40.0)
    grid = cva_eng.cva_sensitivity_grid(metrics['EE'], metrics['ENE'], time_grid,
                                        credit_curve, own_cc)

    section_header("CVA / DVA SENSITIVITY GRID")
    g1 = st.columns(4)
    g1[0].metric("CVA", f"₹{grid['CVA']:.4f} CR", accent="red")
    g1[1].metric("DVA", f"₹{grid['DVA']:.4f} CR", accent="green")
    g1[2].metric("BILATERAL CVA", f"₹{grid['Bilateral_CVA']:.4f} CR", accent="amber")
    g1[3].metric("CDS GAMMA", f"₹{grid['CDS_Gamma']:.6f}/bp²", accent="blue")
    g2 = st.columns(4)
    g2[0].metric("CS01 CVA", f"₹{grid['CS01_CVA']:.6f}/bp", accent="amber")
    g2[1].metric("CS01 DVA", f"₹{grid['CS01_DVA']:.6f}/bp", accent="green")
    g2[2].metric("IR01 CVA", f"₹{grid['IR01_CVA']:.6f}/bp", accent="blue")
    g2[3].metric("IR01 DVA", f"₹{grid['IR01_DVA']:.6f}/bp", accent="blue")

    sens_names = ['CS01_CVA', 'CS01_DVA', 'IR01_CVA', 'IR01_DVA']
    sens_vals = [grid[k] for k in sens_names]
    sens_colors = [COLORS['success'] if v >= 0 else COLORS['danger_bright'] for v in sens_vals]
    figs = go.Figure()
    figs.add_trace(go.Bar(x=sens_names, y=sens_vals, marker=dict(color=sens_colors),
                          text=[f'{v:.5f}' for v in sens_vals], textposition='outside',
                          textfont=dict(family=_MONO, color='#e0e0e0', size=9),
                          hovertemplate='<b>%{x}</b><br>%{y:.6f} ₹Cr/bp<extra></extra>'))
    _apply_bbg_chart(figs, 'CVA / DVA FIRST-ORDER SENSITIVITIES (₹ CR / BP)')
    figs.update_yaxes(title_text='SENSITIVITY (₹ CR/BP)')
    st.plotly_chart(figs, use_container_width=True)

    section_header("CDS HEDGE & EFFECTIVENESS",
                   "CDS notional to delta-hedge CVA + Indian-market hedge effectiveness")
    hedge = CDSHedgeEngine(ois_curve)
    hn = hedge.compute_cds_hedge_notional(metrics['EE'], time_grid, credit_curve,
                                          hedge_tenor=float(maturity))
    var_res = hedge.unhedged_cva_pnl_variance(metrics['EE'], time_grid, credit_curve)

    _sector_map = {'psu': 'PSU_Bank', 'private': 'Private_Bank', 'nbfc': 'NBFC',
                   'stressed': 'Corporate_HY'}
    _et = str(cpty_row.get('entity_type', '')).lower()
    sector = next((v for k, v in _sector_map.items() if k in _et), 'Corporate_IG')
    eff = hedge.hedge_effectiveness(sector, cva_vol=var_res['daily_cva_vol_cr'])

    h = st.columns(4)
    h[0].metric("CDS HEDGE NOTIONAL", f"₹{hn['hedge_notional_cr']:.2f} CR", accent="amber")
    h[1].metric("CDS PREMIUM PV", f"₹{hn['cds_premium_pv_cr']:.4f} CR", accent="red")
    h[2].metric("DAILY CVA VOL", f"₹{var_res['daily_cva_vol_cr']:.4f} CR", accent="blue")
    h[3].metric("CVA VAR 99%", f"₹{var_res['daily_cva_var99_cr']:.4f} CR", accent="red")

    h2 = st.columns(3)
    h2[0].metric("HEDGE TYPE", eff['hedge_type'].upper().replace(' ', '_'), accent="blue")
    h2[1].metric("EFFECTIVENESS", f"{eff['effectiveness']*100:.1f}%", accent="green")
    h2[2].metric("RESIDUAL CVA VOL", f"₹{eff['residual_cva_vol_cr']:.4f} CR", accent="amber")
    st.markdown(f"<div class='assumptions-panel'><div class='ap-title'>INDIA MARKET NOTE</div>"
                f"<div style='font-size:0.7rem;color:#8899aa;line-height:1.5'>{eff['india_market_note']}</div></div>",
                unsafe_allow_html=True)


elif page == "Portfolio WWR (Copula)":
    st.markdown("# Portfolio WWR (Copula)")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "GAUSSIAN COPULA — CORRELATED COUNTERPARTY DEFAULTS WITH RATE-CREDIT WWR</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.wwr.gaussian_copula_wwr import GaussianCopulaWWR, build_empirical_correlation_matrix

    section_header("MODEL INPUTS")
    rate_corr = st.slider("RATE-DEFAULT CORRELATION (ρ)", -0.5, 0.9, 0.40, 0.05)

    _sector_map = {'psu': 'PSU_Bank', 'private': 'Private_Bank', 'nbfc': 'NBFC',
                   'stressed': 'Corporate_HY'}
    names = counterparties['counterparty'].tolist()
    credit_curves = [CreditCurve(r['cds_spread_bps'], r['recovery_rate'])
                     for _, r in counterparties.iterrows()]
    sectors = []
    for _, r in counterparties.iterrows():
        et = str(r['entity_type']).lower()
        sectors.append(next((v for k, v in _sector_map.items() if k in et), 'Corporate_IG'))
    # Heterogeneous EE profiles: scale the active-trade EE by relative CDS level
    base_cds = max(cpty_row['cds_spread_bps'], 1.0)
    ee_profiles = [metrics['EE'] * (r['cds_spread_bps'] / base_cds)
                   for _, r in counterparties.iterrows()]

    rp = rate_paths[:2000]
    model = GaussianCopulaWWR(ois_curve, n_paths=rp.shape[0], seed=42)
    with st.spinner("SIMULATING CORRELATED DEFAULTS..."):
        wwr = model.compute_portfolio_cva_copula(
            names, credit_curves, sectors, ee_profiles, time_grid,
            rate_paths=rp, rate_correlation=rate_corr)

    section_header("PORTFOLIO CVA UNDER COPULA WWR")
    w = st.columns(4)
    w[0].metric("Σ STANDALONE CVA", f"₹{wwr['sum_standalone_cva']:.4f} CR", accent="amber")
    w[1].metric("PORTFOLIO CVA", f"₹{wwr['portfolio_cva_copula']:.4f} CR", accent="red")
    w[2].metric("WWR MULTIPLIER", f"{wwr['wwr_multiplier']:.3f}×", accent="blue")
    w[3].metric("DIVERSIFICATION", f"₹{wwr['diversification_benefit']:.4f} CR", accent="green")

    col1, col2 = st.columns([3, 2])
    with col1:
        section_header("STANDALONE CVA BY COUNTERPARTY")
        sc_names = list(wwr['standalone_cvas'].keys())
        sc_vals = [wwr['standalone_cvas'][n] for n in sc_names]
        figc = go.Figure()
        figc.add_trace(go.Bar(x=sc_names, y=sc_vals, marker=dict(color=COLORS['PFE']),
                              text=[f'₹{v:.3f}' for v in sc_vals], textposition='outside',
                              textfont=dict(family=_MONO, color='#e0e0e0', size=9),
                              hovertemplate='<b>%{x}</b><br>CVA: ₹%{y:.4f} Cr<extra></extra>'))
        _apply_bbg_chart(figc, 'STANDALONE CVA (₹ CR)')
        figc.update_yaxes(title_text='CVA (₹ CR)')
        st.plotly_chart(figc, use_container_width=True)
    with col2:
        section_header("ASSET CORRELATION MATRIX")
        cm = wwr['corr_matrix']
        short_names = [n.split('(')[0].strip()[:10] for n in names]
        figh = go.Figure(data=go.Heatmap(
            z=cm, x=short_names, y=short_names,
            colorscale=[[0, '#0d1117'], [0.5, '#243040'], [1, '#ff6600']],
            zmin=0, zmax=1, showscale=True,
            hovertemplate='%{y} / %{x}<br>ρ=%{z:.2f}<extra></extra>'))
        figh.update_layout(**{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ('xaxis', 'yaxis')},
                           title='BASEL IRB ASSET CORRELATION')
        figh.update_xaxes(tickfont=dict(family=_MONO, color='#8899aa', size=8))
        figh.update_yaxes(tickfont=dict(family=_MONO, color='#8899aa', size=8))
        st.plotly_chart(figh, use_container_width=True)


elif page == "SIMM Initial Margin":
    st.markdown("# SIMM Initial Margin")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "ISDA SIMM v2.7 MULTI-CLASS IM (IR / FX / EQUITY) + CCIL TENOR-SPECIFIC DIM</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.xva.simm import SIMMMultiClassCalculator
    from src.data_ingestion.ccil_data import compute_tenor_specific_dim, CCILDataFetcher

    section_header("MULTI-CLASS IM INPUTS",
                   "IR delta derived from the active trade's DV01; FX & equity deltas are user inputs")
    dv01_inr = abs(swap.dv01(ois_curve)) * 1e7  # ₹ Cr/bp → ₹/bp
    ci = st.columns(3)
    ir_sens = ci[0].number_input("IR DV01 5Y (₹)", value=float(round(dv01_inr)), step=1e5, format="%.0f")
    fx_sens = ci[1].number_input("USD/INR FX DELTA (₹)", value=50_000_000.0, step=1e6, format="%.0f")
    eq_sens = ci[2].number_input("EQUITY DELTA (BUCKET 4, ₹)", value=10_000_000.0, step=1e6, format="%.0f")

    calc = SIMMMultiClassCalculator()
    im = calc.compute_total_im(
        ir_sensitivities={'5Y': ir_sens},
        fx_sensitivities={'USD/INR': fx_sens},
        equity_sensitivities={4: eq_sens})

    section_header("SIMM IM BREAKDOWN")
    s = st.columns(4)
    s[0].metric("IM — IR", f"₹{im['IM_IR']:,.0f}", accent="blue")
    s[1].metric("IM — FX", f"₹{im['IM_FX']:,.0f}", accent="amber")
    s[2].metric("IM — EQUITY", f"₹{im['IM_EQ']:,.0f}", accent="green")
    s[3].metric("IM — TOTAL", f"₹{im['IM_Total']:,.0f}", accent="red")

    col1, col2 = st.columns(2)
    with col1:
        figd = go.Figure(data=[go.Pie(
            labels=['IR', 'FX', 'EQUITY'],
            values=[im['IM_IR'], im['IM_FX'], im['IM_EQ']],
            hole=0.55, sort=False,
            marker=dict(colors=[COLORS['EE'], COLORS['EPE'], COLORS['ENE']],
                        line=dict(color='#0d1117', width=2)),
            textfont=dict(family=_MONO, color='#0d1117', size=11),
            hovertemplate='<b>%{label}</b><br>₹%{value:,.0f}<br>%{percent}<extra></extra>')])
        figd.update_layout(**{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ('xaxis', 'yaxis')},
                           title='IM BY RISK CLASS', showlegend=True)
        st.plotly_chart(figd, use_container_width=True)
    with col2:
        section_header("CCIL TENOR-SPECIFIC DIM PROFILE")
        kr = swap.key_rate_dv01(ois_curve)
        dv01_by_tenor = {}
        for k, v in kr.items():
            digits = ''.join(ch for ch in str(k) if ch.isdigit() or ch == '.')
            try:
                yrs = int(round(float(digits)))
            except ValueError:
                continue
            lbl = {1: '1Y', 2: '2Y', 3: '3Y', 5: '5Y', 7: '7Y', 10: '10Y'}.get(yrs)
            if lbl:
                dv01_by_tenor[lbl] = dv01_by_tenor.get(lbl, 0.0) + abs(v)
        if not dv01_by_tenor:
            dv01_by_tenor = {'5Y': abs(swap.dv01(ois_curve))}
        dim = compute_tenor_specific_dim(float(maturity), time_grid, dv01_by_tenor)
        figm = go.Figure()
        figm.add_trace(go.Scatter(x=time_grid, y=dim, name='DIM', mode='lines',
                                  line=dict(color=COLORS['EPE'], width=2.5),
                                  fill='tozeroy', fillcolor='rgba(255,170,0,0.08)',
                                  hovertemplate='DIM: ₹%{y:.4f} Cr<extra></extra>'))
        _apply_bbg_chart(figm, 'CCIL TENOR-SPECIFIC DIM (₹ CR)')
        figm.update_xaxes(title_text='TIME (YEARS)')
        figm.update_yaxes(title_text='DIM (₹ CR)')
        st.plotly_chart(figm, use_container_width=True)

    with st.expander("CCIL MIBOR TERM VOLATILITY STRUCTURE"):
        vols = CCILDataFetcher().get_tenor_specific_vol()
        vrows = "".join(f"<tr><td>{t}</td><td class='num-warn'>{v:.0f}</td></tr>" for t, v in vols.items())
        st.markdown(f"<div class='bbg-table-wrap'><table class='bbg-table'><thead><tr>"
                    f"<th>TENOR</th><th>NORMAL VOL (BPS)</th></tr></thead>"
                    f"<tbody>{vrows}</tbody></table></div>", unsafe_allow_html=True)


elif page == "CSA CTD Optionality":
    st.markdown("# CSA CTD Optionality")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "CHEAPEST-TO-DELIVER COLLATERAL — RBI-ELIGIBLE SET — ISDA CSA</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.csa.ctd_optionality import CTDEngine, get_standard_rbi_collateral_set

    section_header("MARKET INPUTS", "Repo / OIS / G-Sec yields anchored to RBI & FBIL free fixings")
    mi = st.columns(3)
    repo = mi[0].slider("REPO RATE (%)", 4.0, 9.0, 6.5, 0.05) / 100
    ois_r = mi[1].slider("OIS RATE (%)", 4.0, 9.0, 6.8, 0.05) / 100
    gsec10 = mi[2].slider("G-SEC 10Y (%)", 5.0, 9.0, 7.2, 0.05) / 100

    assets = get_standard_rbi_collateral_set(repo_rate=repo, gsec_10y=gsec10)
    eng = CTDEngine(ois_rate=ois_r)
    ctd = eng.find_ctd(assets, repo)
    fva = eng.ctd_adjusted_fva(metrics['EE'], time_grid, assets, repo, ois_curve)

    section_header("CHEAPEST-TO-DELIVER RESULT")
    c = st.columns(4)
    c[0].metric("CTD ASSET", ctd['ctd_asset']['name'].upper(), accent="green")
    c[1].metric("OPTIONALITY SPREAD", f"{ctd['ctd_optionality_spread_bps']:.1f} BPS", accent="amber")
    c[2].metric("CTD-FVA (ACTIVE)", f"₹{fva['CTD_FVA']:.4f} CR", accent="amber")
    c[3].metric("N ELIGIBLE", str(ctd['n_eligible']), accent="blue")

    section_header("ELIGIBLE COLLATERAL CARRY-COST LADDER")
    crows = ""
    for a in ctd['all_assets']:
        is_ctd = (a['name'] == ctd['ctd_asset']['name'])
        cls = "num-pos" if is_ctd else ""
        flag = " ◄ CTD" if is_ctd else ""
        crows += (f"<tr><td class='{cls}'>{a['name']}{flag}</td>"
                  f"<td>{a['yield_pct']*100:.2f}%</td>"
                  f"<td>{a['haircut_pct']*100:.2f}%</td>"
                  f"<td class='{cls}'>{a['net_carry_cost']*10000:.1f}</td>"
                  f"<td>{a['liquidity_score']}</td></tr>")
    st.markdown(f"<div class='bbg-table-wrap'><table class='bbg-table'><thead><tr>"
                f"<th>ASSET</th><th>YIELD</th><th>HAIRCUT</th>"
                f"<th>NET CARRY (BPS)</th><th>LIQUIDITY</th>"
                f"</tr></thead><tbody>{crows}</tbody></table></div>", unsafe_allow_html=True)

    asset_names = [a['name'] for a in ctd['all_assets']]
    carry_bps = [a['net_carry_cost'] * 10000 for a in ctd['all_assets']]
    carry_colors = [COLORS['success'] if a['name'] == ctd['ctd_asset']['name']
                    else COLORS['EE'] for a in ctd['all_assets']]
    figc = go.Figure()
    figc.add_trace(go.Bar(x=asset_names, y=carry_bps, marker=dict(color=carry_colors),
                          text=[f'{v:.1f}' for v in carry_bps], textposition='outside',
                          textfont=dict(family=_MONO, color='#e0e0e0', size=9),
                          hovertemplate='<b>%{x}</b><br>Net carry: %{y:.1f} bps<extra></extra>'))
    _apply_bbg_chart(figc, 'NET CARRY COST BY ELIGIBLE COLLATERAL (LOWEST = CTD)')
    figc.update_yaxes(title_text='NET CARRY (BPS)')
    st.plotly_chart(figc, use_container_width=True)


# ═════════════════════════════════════════════════════════════
# ADVANCED QUANT PAGES (AAD, QMC, LSM, FX-XVA, stochastic WWR,
#                       BA-CVA, exposure backtest, IFRS-13)
# ═════════════════════════════════════════════════════════════
elif page == "AAD Greeks Engine":
    st.markdown("# AAD Greeks Engine")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "ADJOINT ALGORITHMIC DIFFERENTIATION — FULL CVA GREEK VECTOR IN ONE REVERSE SWEEP</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.xva.aad_greeks import AADCVAEngine

    section_header("AAD vs BUMP-AND-REVALUE",
                   "AAD computes the entire gradient (CS01, IR01, recovery, and every exposure-bucket "
                   "delta) in ~1 valuation; bump-and-revalue needs one revaluation per sensitivity.")
    aad = AADCVAEngine(ois_curve)
    out = aad.cva_and_greeks(metrics['EE'], time_grid, credit_curve)
    bm = aad.benchmark_vs_bump(metrics['EE'], time_grid, credit_curve, n_reps=40)

    cols = st.columns(4)
    cols[0].metric("CVA", f"₹{out['CVA']:.4f} CR", accent="red")
    cols[1].metric("SENSITIVITIES / SWEEP", str(out['n_sensitivities']), accent="green")
    cols[2].metric("AAD REVALUATIONS", str(bm['aad_revaluations']), accent="blue")
    cols[3].metric("BUMP REVALUATIONS", str(bm['bump_revaluations']), accent="amber")

    c2 = st.columns(4)
    c2[0].metric("CS01 (AAD)", f"₹{out['CS01']:.6f}/bp", accent="amber")
    c2[1].metric("IR01 (AAD)", f"₹{out['IR01']:.6f}/bp", accent="blue")
    c2[2].metric("RECOVERY01", f"₹{out['Recovery01']:.6f}/%", accent="green")
    c2[3].metric("MAX GREEK ERR vs BUMP", f"{bm['EE_delta_max_abs_err']:.1e}", accent="green")

    section_header("EXPOSURE-BUCKET GREEKS (dCVA / dEE_i) — ALL FROM ONE SWEEP")
    figg = go.Figure()
    figg.add_trace(go.Bar(x=time_grid, y=out['EE_deltas'], marker=dict(color=COLORS['EE']),
                          hovertemplate='t=%{x:.2f}Y<br>dCVA/dEE=%{y:.5f}<extra></extra>'))
    _apply_bbg_chart(figg, 'CVA SENSITIVITY TO EACH EXPOSURE NODE')
    figg.update_xaxes(title_text='TIME (YEARS)')
    figg.update_yaxes(title_text='dCVA / dEE_i')
    st.plotly_chart(figg, use_container_width=True)

    st.markdown(f"<div class='assumptions-panel'><div class='ap-title'>WHY THIS MATTERS</div>"
                f"<div style='font-size:0.7rem;color:#8899aa;line-height:1.5'>"
                f"On this {len(time_grid)}-node grid, AAD returns {out['n_sensitivities']} exact "
                f"sensitivities from a single reverse sweep, versus {bm['bump_revaluations']} full "
                f"revaluations for bump-and-revalue — and the agreement is "
                f"{bm['EE_delta_max_abs_err']:.1e}. This is the technique every Tier-1 bank uses for "
                f"real-time XVA Greeks. Engine: self-contained reverse-mode autodiff (pure NumPy, no "
                f"JAX/PyTorch).</div></div>", unsafe_allow_html=True)


elif page == "Quasi-Monte Carlo":
    st.markdown("# Quasi-Monte Carlo")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "SOBOL LOW-DISCREPANCY SEQUENCES + BROWNIAN BRIDGE — VARIANCE REDUCTION</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.montecarlo.quasi_mc import convergence_demo

    section_header("MC vs QMC CONVERGENCE (vs ANALYTIC TRUTH)",
                   "ATM Bachelier swaption priced by pseudo-random MC and Sobol QMC at rising path "
                   "counts, compared to the exact closed-form price.")
    demo = convergence_demo(path_counts=(256, 512, 1024, 2048, 4096, 8192))
    st.metric("ANALYTIC PRICE", f"₹{demo['analytic']:.4f} CR", accent="green")

    rows = demo['rows']
    rrows = ""
    for r in rows:
        better = r['qmc_abs_err'] < r['mc_abs_err']
        rrows += (f"<tr><td>{r['n_paths']:,}</td>"
                  f"<td>₹{r['mc_price']:.4f}</td><td>₹{r['qmc_price']:.4f}</td>"
                  f"<td class='num-neg'>{r['mc_abs_err']:.5f}</td>"
                  f"<td class='{'num-pos' if better else 'num-warn'}'>{r['qmc_abs_err']:.5f}</td></tr>")
    st.markdown(f"<div class='bbg-table-wrap'><table class='bbg-table'><thead><tr>"
                f"<th>N PATHS</th><th>MC PRICE</th><th>QMC PRICE</th>"
                f"<th>MC ABS ERR</th><th>QMC ABS ERR</th>"
                f"</tr></thead><tbody>{rrows}</tbody></table></div>", unsafe_allow_html=True)

    figq = go.Figure()
    figq.add_trace(go.Scatter(x=[r['n_paths'] for r in rows], y=[r['mc_abs_err'] for r in rows],
                              name='MC ERROR', mode='lines+markers',
                              line=dict(color=COLORS['PFE'], width=2.5),
                              hovertemplate='N=%{x}<br>err=%{y:.5f}<extra></extra>'))
    figq.add_trace(go.Scatter(x=[r['n_paths'] for r in rows], y=[r['qmc_abs_err'] for r in rows],
                              name='QMC (SOBOL) ERROR', mode='lines+markers',
                              line=dict(color=COLORS['ENE'], width=2.5),
                              hovertemplate='N=%{x}<br>err=%{y:.5f}<extra></extra>'))
    _apply_bbg_chart(figq, 'PRICING ERROR vs PATH COUNT (LOG-LOG)')
    figq.update_xaxes(title_text='PATHS', type='log')
    figq.update_yaxes(title_text='ABS ERROR (₹ CR)', type='log')
    st.plotly_chart(figq, use_container_width=True)


elif page == "Bermudan Exposure (LSM)":
    st.markdown("# Bermudan Exposure (LSM)")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "LONGSTAFF-SCHWARTZ — CALLABLE / BERMUDAN SWAPTION EXPOSURE WITH EARLY EXERCISE</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.montecarlo.longstaff_schwartz import BermudanSwaptionLSM

    section_header("BERMUDAN SWAPTION SETUP")
    bc = st.columns(3)
    b_strike = bc[0].number_input("STRIKE (%)", value=7.0, step=0.1) / 100
    b_optn = bc[1].selectbox("TYPE", ["Payer", "Receiver"])
    b_sigma = bc[2].slider("HW1F σ", 0.005, 0.025, 0.012, 0.001)
    ex_dates = [float(y) for y in range(2, int(maturity)) if y < maturity] or [max(1.0, maturity - 1)]

    berm = BermudanSwaptionLSM(ois_curve, notional, b_strike, ex_dates, float(maturity),
                               payer=(b_optn == "Payer"), a=mean_rev, sigma=b_sigma)
    with st.spinner("RUNNING LONGSTAFF-SCHWARTZ..."):
        r = berm.price_and_exposure(n_paths=int(min(n_paths, 6000)), n_steps_per_year=4, seed=42)

    section_header("PRICING & EARLY-EXERCISE")
    bcc = st.columns(4)
    bcc[0].metric("BERMUDAN PV", f"₹{r['price']:.4f} CR", accent="green")
    bcc[1].metric("EUROPEAN REF", f"₹{r['european_ref']:.4f} CR", accent="amber")
    bcc[2].metric("EARLY-EX PREMIUM", f"₹{r['price']-r['european_ref']:.4f} CR", accent="blue")
    bcc[3].metric("EXERCISE FRACTION", f"{r['exercise_fraction']*100:.1f}%", accent="amber")

    section_header("CALLABLE EXPOSURE PROFILE")
    figb = go.Figure()
    figb.add_trace(go.Scatter(x=r['time_grid'], y=r['PFE'], name='PFE 95%', mode='lines',
                              line=dict(color=COLORS['PFE'], width=2),
                              hovertemplate='PFE: ₹%{y:.4f} Cr<extra></extra>'))
    figb.add_trace(go.Scatter(x=r['time_grid'], y=r['EE'], name='EE', mode='lines',
                              line=dict(color=COLORS['EE'], width=2.5), fill='tozeroy',
                              fillcolor='rgba(0,170,255,0.06)',
                              hovertemplate='EE: ₹%{y:.4f} Cr<extra></extra>'))
    for ed in ex_dates:
        figb.add_vline(x=ed, line_dash='dot', line_color='#556677',
                       annotation_text=f'EX {ed:.0f}Y', annotation_font=dict(color='#8899aa', size=8))
    _apply_bbg_chart(figb, 'BERMUDAN EXPOSURE (EARLY EXERCISE COLLAPSES TAIL)')
    figb.update_layout(hovermode='x unified')
    figb.update_xaxes(title_text='TIME (YEARS)')
    figb.update_yaxes(title_text='EXPOSURE (₹ CR)')
    st.plotly_chart(figb, use_container_width=True)


elif page == "Cross-Currency XVA":
    st.markdown("# Cross-Currency XVA")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "3-FACTOR (INR IR / USD IR / USD-INR FX) CROSS-CURRENCY SWAP EXPOSURE</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.montecarlo.cross_currency import CrossCurrencySwapModel

    section_header("MODEL INPUTS")
    xc = st.columns(4)
    usd_rate = xc[0].slider("USD RATE (%)", 3.0, 7.0, 5.3, 0.1) / 100
    fx0 = xc[1].number_input("USD/INR SPOT", value=84.0, step=0.5)
    fxvol = xc[2].slider("USD/INR VOL (%)", 2.0, 12.0, 5.0, 0.5) / 100
    for_fixed = xc[3].number_input("USD FIXED (%)", value=4.5, step=0.1) / 100

    m = CrossCurrencySwapModel(ois_curve, for_rate=usd_rate, fx_spot=fx0, fx_vol=fxvol)
    tg = np.linspace(0, float(maturity), 61)
    with st.spinner("SIMULATING 3-FACTOR DYNAMICS..."):
        sim = m.simulate(int(min(n_paths, 5000)), tg, seed=42)
        mtm = m.swap_mtm_paths(sim, notional, fixed_rate, for_fixed, float(maturity))
        em = m.exposure_metrics(mtm, tg)

    section_header("CCS EXPOSURE (₹ CR)")
    xcc = st.columns(4)
    xcc[0].metric("EPE", f"₹{em['EPE']:.3f} CR", accent="blue")
    xcc[1].metric("MAX EE", f"₹{np.max(em['EE']):.3f} CR", accent="amber")
    xcc[2].metric("MAX PFE 95%", f"₹{np.max(em['PFE']):.3f} CR", accent="red")
    xcc[3].metric("FX TERMINAL (MEAN)", f"{sim['FX'][:,-1].mean():.2f}", accent="green")

    col1, col2 = st.columns(2)
    with col1:
        section_header("EXPOSURE PROFILE")
        figx = go.Figure()
        figx.add_trace(go.Scatter(x=tg, y=em['PFE'], name='PFE 95%', mode='lines',
                                  line=dict(color=COLORS['PFE'], width=2),
                                  hovertemplate='PFE: ₹%{y:.3f} Cr<extra></extra>'))
        figx.add_trace(go.Scatter(x=tg, y=em['EE'], name='EE', mode='lines',
                                  line=dict(color=COLORS['EE'], width=2.5), fill='tozeroy',
                                  fillcolor='rgba(0,170,255,0.06)',
                                  hovertemplate='EE: ₹%{y:.3f} Cr<extra></extra>'))
        _apply_bbg_chart(figx, 'CCS EXPOSURE — PFE PEAKS AT NOTIONAL EXCHANGE')
        figx.update_xaxes(title_text='TIME (YEARS)')
        figx.update_yaxes(title_text='EXPOSURE (₹ CR)')
        st.plotly_chart(figx, use_container_width=True)
    with col2:
        section_header("SIMULATED USD/INR FX PATHS")
        figf = go.Figure()
        for i in range(min(100, sim['FX'].shape[0])):
            figf.add_trace(go.Scatter(x=tg, y=sim['FX'][i], mode='lines',
                                      line=dict(color=COLORS['EPE'], width=0.4),
                                      opacity=0.08, showlegend=False))
        figf.add_trace(go.Scatter(x=tg, y=sim['FX'].mean(0), name='MEAN FX', mode='lines',
                                  line=dict(color=COLORS['ENE'], width=2.5),
                                  hovertemplate='FX: %{y:.2f}<extra></extra>'))
        _apply_bbg_chart(figf, 'USD/INR PATHS (CARRY DRIFT = r_d - r_f)')
        figf.update_xaxes(title_text='TIME (YEARS)')
        figf.update_yaxes(title_text='USD/INR')
        st.plotly_chart(figf, use_container_width=True)


elif page == "Stochastic WWR":
    st.markdown("# Stochastic WWR")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "COX PROCESS — CIR DEFAULT INTENSITY CORRELATED WITH RATES (DYNAMIC WRONG-WAY RISK)</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.wwr.stochastic_intensity_wwr import StochasticIntensityWWR

    section_header("MODEL INPUTS")
    sc = st.columns(4)
    rho_w = sc[0].slider("RATE-INTENSITY CORR (ρ)", -0.8, 0.8, 0.5, 0.1)
    theta = sc[1].slider("LONG-RUN INTENSITY θ", 0.01, 0.10, 0.03, 0.005)
    xi = sc[2].slider("INTENSITY VOL ξ", 0.02, 0.20, 0.08, 0.01)
    w_optn = sc[3].selectbox("SWAP TYPE", ["Payer", "Receiver"])

    w = StochasticIntensityWWR(ois_curve, kappa=0.5, theta=theta, xi=xi, recovery=0.40)
    with st.spinner("SIMULATING CORRELATED RATE + INTENSITY..."):
        res = w.wwr_multiplier(notional, fixed_rate, float(maturity), rho=rho_w,
                               payer=(w_optn == "Payer"), n_paths=int(min(n_paths, 8000)), seed=7)

    section_header("WWR-CVA RESULT")
    wc = st.columns(4)
    wc[0].metric("CVA (WWR)", f"₹{res['CVA_wwr']:.4f} CR", accent="red")
    wc[1].metric("CVA (INDEP)", f"₹{res['CVA_independent']:.4f} CR", accent="amber")
    wc[2].metric("WWR MULTIPLIER", f"{res['wwr_multiplier']:.3f}×",
                 accent=("red" if res['wwr_multiplier'] > 1 else "green"))
    wc[3].metric("DEFAULT PROB", f"{res['default_prob']*100:.1f}%", accent="blue")

    direction_note = ("WRONG-WAY: exposure and default rise together — CVA inflated."
                      if res['wwr_multiplier'] > 1 else
                      "RIGHT-WAY: exposure falls as default rises — CVA reduced.")
    st.markdown(f"<div class='assumptions-panel'><div class='ap-title'>INTERPRETATION (ρ={rho_w:+.1f})</div>"
                f"<div style='font-size:0.7rem;color:#8899aa;line-height:1.5'>{direction_note} "
                f"The multiplier comes from the *dynamics* (correlated CIR intensity), not a static "
                f"correlation fudge — the marginal default probability is held fixed.</div></div>",
                unsafe_allow_html=True)

    section_header("EXPOSURE PROFILE")
    figw = go.Figure()
    figw.add_trace(go.Scatter(x=res['time_grid'], y=res['PFE'], name='PFE 95%', mode='lines',
                              line=dict(color=COLORS['PFE'], width=2),
                              hovertemplate='PFE: ₹%{y:.4f} Cr<extra></extra>'))
    figw.add_trace(go.Scatter(x=res['time_grid'], y=res['EE'], name='EE', mode='lines',
                              line=dict(color=COLORS['EE'], width=2.5), fill='tozeroy',
                              fillcolor='rgba(0,170,255,0.06)',
                              hovertemplate='EE: ₹%{y:.4f} Cr<extra></extra>'))
    _apply_bbg_chart(figw, 'SWAP EXPOSURE DRIVING THE WWR-CVA')
    figw.update_xaxes(title_text='TIME (YEARS)')
    figw.update_yaxes(title_text='EXPOSURE (₹ CR)')
    st.plotly_chart(figw, use_container_width=True)


elif page == "BA-CVA Capital":
    st.markdown("# BA-CVA Capital")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "BASEL BASIC APPROACH CVA — REDUCED & FULL (HEDGED) — BIS d424</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.sa_ccr.ba_cva import BACVAEngine
    from src.sa_ccr.regulatory import SACCRCalculator

    section_header("PORTFOLIO EAD & MATURITY (FROM SA-CCR)")
    saccr = SACCRCalculator()
    cptys_ba = []
    for _, row in counterparties.iterrows():
        addon = saccr.compute_trade_addon(notional=notional, maturity=float(maturity), direction=direction)
        ead = 1.4 * (max(swap.mtm(ois_curve), 0.0) + addon['trade_addon'])
        sector = 'Financial' if 'Bank' in str(row['entity_type']) or 'NBFC' in str(row['entity_type']) else 'Other'
        cptys_ba.append({'name': row['counterparty'], 'sector': sector,
                         'rating': row['rating'], 'ead': ead, 'maturity': float(maturity)})

    beta = st.slider("RECOGNISED HEDGE FRACTION β", 0.0, 0.9, 0.3, 0.05)
    eng = BACVAEngine()
    red = eng.compute_reduced(cptys_ba)
    full = eng.compute_full(cptys_ba, beta=beta)

    section_header("CAPITAL RESULT")
    bc = st.columns(4)
    bc[0].metric("K REDUCED", f"₹{red['K_reduced']:.4f} CR", accent="amber")
    bc[1].metric("K FULL (HEDGED)", f"₹{full['K_full']:.4f} CR", accent="green")
    bc[2].metric("BA-CVA CAPITAL", f"₹{full['BA_CVA_capital_full_CR']:.4f} CR", accent="red")
    bc[3].metric("SYSTEMATIC / IDIO", f"{red['systematic_component']:.2f} / {red['idiosyncratic_component']:.2f}",
                 accent="blue")

    section_header("STANDALONE CVA CAPITAL (SCVA) BY COUNTERPARTY")
    drows = ""
    for d in red['details']:
        drows += (f"<tr><td>{d['name']}</td><td>{d['rw_pct']:.1f}</td>"
                  f"<td>₹{d['ead']:.3f}</td><td>{d['maturity']:.1f}</td>"
                  f"<td class='num-warn'>₹{d['scva']:.4f}</td></tr>")
    st.markdown(f"<div class='bbg-table-wrap'><table class='bbg-table'><thead><tr>"
                f"<th>COUNTERPARTY</th><th>RW (%)</th><th>EAD (₹CR)</th><th>MATURITY</th>"
                f"<th>SCVA (₹CR)</th></tr></thead><tbody>{drows}</tbody></table></div>",
                unsafe_allow_html=True)

    figba = go.Figure()
    nm = [d['name'] for d in red['details']]; sv = [d['scva'] for d in red['details']]
    figba.add_trace(go.Bar(x=nm, y=sv, marker=dict(color=COLORS['EPE']),
                           text=[f'₹{v:.3f}' for v in sv], textposition='outside',
                           textfont=dict(family=_MONO, color='#e0e0e0', size=9),
                           hovertemplate='<b>%{x}</b><br>SCVA: ₹%{y:.4f} Cr<extra></extra>'))
    _apply_bbg_chart(figba, 'STANDALONE CVA CAPITAL CONTRIBUTION')
    figba.update_yaxes(title_text='SCVA (₹ CR)')
    st.plotly_chart(figba, use_container_width=True)


elif page == "Exposure Backtesting":
    st.markdown("# Exposure Backtesting")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "IMM MODEL VALIDATION — KUPIEC POF TEST + BASEL TRAFFIC-LIGHT ZONING</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.validation.exposure_backtest import ExposureBacktester

    section_header("BACKTEST SETUP")
    bk = st.columns(3)
    q_level = bk[0].slider("PFE QUANTILE", 0.90, 0.99, 0.95, 0.01)
    stress = bk[1].slider("REALISED STRESS FACTOR", 0.8, 2.0, 1.0, 0.1,
                          help="Scale realised vol; >1 makes the model under-predict")
    seed_bt = int(bk[2].number_input("SEED", value=7, step=1))

    bt = ExposureBacktester(quantile=q_level)
    res = bt.backtest_from_simulation(mtm_paths, time_grid, realised_factor=stress, seed=seed_bt)
    tl = res['traffic_light']; kup = res['kupiec']

    section_header("BACKTEST RESULT")
    zone_accent = {'GREEN': 'green', 'AMBER': 'amber', 'RED': 'red'}.get(tl['zone'], 'blue')
    rc = st.columns(4)
    rc[0].metric("TRAFFIC LIGHT", tl['zone'], accent=zone_accent)
    rc[1].metric("BREACHES", f"{res['n_breaches']} / {res['n_observations']}", accent="amber")
    rc[2].metric("CAPITAL MULTIPLIER", f"{tl['capital_multiplier']:.2f}×", accent=zone_accent)
    rc[3].metric("KUPIEC REJECT H0", "YES" if kup['reject_H0'] else "NO",
                 accent=("red" if kup['reject_H0'] else "green"))

    rc2 = st.columns(3)
    rc2[0].metric("BREACH RATE", f"{res['breach_rate']*100:.2f}%", accent="amber")
    rc2[1].metric("EXPECTED RATE", f"{res['expected_breach_rate']*100:.2f}%", accent="blue")
    rc2[2].metric("KUPIEC p-VALUE", f"{kup['p_value']:.3f}", accent="blue")

    section_header("PREDICTED PFE vs REALISED EXPOSURE")
    figbt = go.Figure()
    figbt.add_trace(go.Scatter(x=res['time_grid'], y=res['predicted_pfe'],
                               name=f'PREDICTED PFE {q_level:.0%}', mode='lines',
                               line=dict(color=COLORS['EPE'], width=2.5),
                               hovertemplate='PFE: ₹%{y:.3f} Cr<extra></extra>'))
    realised = res['realised']
    breach_mask = realised > res['predicted_pfe']
    figbt.add_trace(go.Scatter(x=res['time_grid'], y=realised, name='REALISED', mode='markers',
                               marker=dict(color=np.where(breach_mask, '#ff3311', '#00aaff'),
                                           size=5),
                               hovertemplate='realised: ₹%{y:.3f} Cr<extra></extra>'))
    _apply_bbg_chart(figbt, 'BACKTEST — RED MARKERS ARE QUANTILE BREACHES')
    figbt.update_xaxes(title_text='OBSERVATION (TIME)')
    figbt.update_yaxes(title_text='EXPOSURE (₹ CR)')
    st.plotly_chart(figbt, use_container_width=True)


elif page == "IFRS-13 Accounting":
    st.markdown("# IFRS-13 Accounting")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "XVA FAIR-VALUE RESERVE & P&L ATTRIBUTION — IFRS 13 FAIR-VALUE MEASUREMENT</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.xva.ifrs13 import XVAReserve, IFRS13XVAReporter

    section_header("XVA RESERVE INPUTS (₹ CR)")
    ic = st.columns(5)
    in_cva = ic[0].number_input("CVA", value=4.20, step=0.05)
    in_dva = ic[1].number_input("DVA", value=0.80, step=0.05)
    in_fva = ic[2].number_input("FVA", value=1.10, step=0.05)
    in_mva = ic[3].number_input("MVA", value=0.30, step=0.05)
    in_kva = ic[4].number_input("KVA", value=2.00, step=0.05)
    incl_kva = st.checkbox("INCLUDE KVA IN FAIR VALUE", value=False)

    rep = IFRS13XVAReporter()
    curr = XVAReserve(cva=in_cva, dva=in_dva, fva=in_fva, mva=in_mva, kva=in_kva)
    stmt = rep.fair_value_statement(curr, include_kva=incl_kva)

    section_header("FAIR-VALUE STATEMENT")
    sc = st.columns(3)
    sc[0].metric("NET FV ADJUSTMENT", f"₹{stmt['net_fv_adjustment_CR']:.3f} CR", accent="red")
    sc[1].metric("GROSS XVA RESERVE", f"₹{stmt['gross_xva_reserve_CR']:.3f} CR", accent="amber")
    sc[2].metric("OWN-CREDIT (DVA) BENEFIT", f"₹{stmt['own_credit_benefit_CR']:.3f} CR", accent="green")

    crows = ""
    for name, c in stmt['components'].items():
        sgn = "num-pos" if c['fv_sign'] >= 0 else "num-neg"
        crows += (f"<tr><td>{name}</td><td>₹{c['amount']:.3f}</td>"
                  f"<td class='{sgn}'>₹{c['fv_sign']:+.3f}</td>"
                  f"<td>{c['hierarchy']}</td><td>{c['note']}</td></tr>")
    st.markdown(f"<div class='bbg-table-wrap'><table class='bbg-table'><thead><tr>"
                f"<th>COMPONENT</th><th>AMOUNT</th><th>FV IMPACT</th>"
                f"<th>IFRS-13 LEVEL</th><th>NOTE</th></tr></thead>"
                f"<tbody>{crows}</tbody></table></div>", unsafe_allow_html=True)

    section_header("DAY-OVER-DAY XVA P&L ATTRIBUTION")
    pc = st.columns(5)
    p_cva = pc[0].number_input("Δ CVA → today", value=4.65, step=0.05)
    p_dva = pc[1].number_input("Δ DVA → today", value=0.70, step=0.05)
    p_fva = pc[2].number_input("Δ FVA → today", value=1.30, step=0.05)
    p_mva = pc[3].number_input("Δ MVA → today", value=0.35, step=0.05)
    p_kva = pc[4].number_input("Δ KVA → today", value=2.10, step=0.05)
    today = XVAReserve(cva=p_cva, dva=p_dva, fva=p_fva, mva=p_mva, kva=p_kva)
    pnl = rep.pnl_attribution(curr, today, include_kva=incl_kva)

    st.metric("TOTAL XVA P&L", f"₹{pnl['total_xva_pnl_CR']:+.3f} CR",
              accent=("green" if pnl['total_xva_pnl_CR'] >= 0 else "red"))
    effects = list(pnl['lines'].keys()); vals = list(pnl['lines'].values())
    figp = go.Figure(go.Waterfall(
        orientation="v", measure=["relative"] * len(effects) + ["total"],
        x=[e.replace('_pnl', '').upper() for e in effects] + ['TOTAL'],
        y=vals + [pnl['total_xva_pnl_CR']],
        text=[f"₹{v:+.3f}" for v in vals + [pnl['total_xva_pnl_CR']]],
        textposition='outside', textfont=dict(family=_MONO, color='#e0e0e0', size=9),
        connector={"line": {"color": "#243040"}},
        increasing={"marker": {"color": COLORS['success']}},
        decreasing={"marker": {"color": COLORS['danger_bright']}},
        totals={"marker": {"color": COLORS['EE']}}))
    _apply_bbg_chart(figp, 'XVA P&L WATERFALL (DAY-OVER-DAY)')
    st.plotly_chart(figp, use_container_width=True)


# ═════════════════════════════════════════════════════════════
# EQUITY & HYBRID CROSS-ASSET PAGES
# ═════════════════════════════════════════════════════════════
elif page == "Equity Derivatives":
    st.markdown("# Equity Derivatives")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "NSE NIFTY / BANK NIFTY OPTIONS — BSM + VOL SMILE — EQUITY EXPOSURE (FREE NSE DATA)</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.pricing.equity_options import EquityVolSmile, bsm_greeks
    from src.montecarlo.equity_mc import EquityGBM

    section_header("EQUITY MARKET DATA")
    eq_index = st.selectbox("INDEX", ["NIFTY", "BANKNIFTY"])
    eqmd = cached_equity_market_data(eq_index)
    chain = cached_nifty_option_chain(eq_index, eqmd['spot'], eqmd['atm_vol'])
    smile = EquityVolSmile.from_chain(chain, eqmd['atm_vol'])

    em_cols = st.columns(5)
    em_cols[0].metric("SPOT", f"{eqmd['spot']:,.0f}", accent="blue")
    em_cols[1].metric("ATM VOL", f"{eqmd['atm_vol']*100:.1f}%", accent="amber")
    em_cols[2].metric("INDIA VIX", f"{eqmd['india_vix']:.1f}", accent="red")
    em_cols[3].metric("DIV YIELD", f"{eqmd['div_yield']*100:.2f}%", accent="green")
    em_cols[4].metric("LOT SIZE", str(eqmd['lot_size']), accent="blue")
    st.markdown(f"<div style='color:#556677;font-size:0.6rem'>SOURCE: {eqmd['source']}</div>",
                unsafe_allow_html=True)

    section_header("OPTION PRICING")
    oc = st.columns(4)
    o_strike = oc[0].number_input("STRIKE", value=float(round(eqmd['spot'] / 100) * 100), step=100.0)
    o_expiry = oc[1].slider("EXPIRY (YRS)", 0.08, 2.0, 0.25, 0.02)
    o_type = oc[2].selectbox("TYPE", ["Call", "Put"])
    o_lots = oc[3].number_input("LOTS", value=10, step=1)
    r_eq = ois_curve.zero_rate(max(o_expiry, 0.1))
    fwd = eqmd['spot'] * np.exp((r_eq - eqmd['div_yield']) * o_expiry)
    o_vol = smile.vol(o_strike, fwd)
    from src.pricing.equity_options import bsm_price
    units = eqmd['lot_size'] * o_lots
    px = units * bsm_price(eqmd['spot'], o_strike, o_expiry, r_eq, eqmd['div_yield'], o_vol, o_type == "Call")
    g = bsm_greeks(eqmd['spot'], o_strike, o_expiry, r_eq, eqmd['div_yield'], o_vol, o_type == "Call")

    pc = st.columns(5)
    pc[0].metric("OPTION VALUE", f"₹{px:,.0f}", accent="green")
    pc[1].metric("SMILE VOL", f"{o_vol*100:.2f}%", accent="amber")
    pc[2].metric("DELTA", f"{g['delta']*units:,.0f}", accent="blue")
    pc[3].metric("GAMMA", f"{g['gamma']*units:.2f}", accent="blue")
    pc[4].metric("VEGA (per %)", f"₹{g['vega']*units*0.01:,.0f}", accent="amber")

    col1, col2 = st.columns(2)
    with col1:
        section_header("VOLATILITY SMILE")
        figsm = go.Figure()
        figsm.add_trace(go.Scatter(x=chain['strike'], y=chain['implied_vol'] * 100,
                                   name='IMPLIED VOL', mode='lines+markers',
                                   line=dict(color=COLORS['EPE'], width=2.5),
                                   hovertemplate='K=%{x:,.0f}<br>vol=%{y:.2f}%<extra></extra>'))
        figsm.add_vline(x=eqmd['spot'], line_dash='dot', line_color=COLORS['EE'],
                        annotation_text='SPOT', annotation_font=dict(color='#00aaff', size=9))
        _apply_bbg_chart(figsm, f'{eq_index} VOL SMILE (NEGATIVE EQUITY SKEW)')
        figsm.update_xaxes(title_text='STRIKE')
        figsm.update_yaxes(title_text='IMPLIED VOL (%)')
        st.plotly_chart(figsm, use_container_width=True)
    with col2:
        section_header("EQUITY EXPOSURE PROFILE")
        gbm = EquityGBM(eqmd['spot'], eqmd['atm_vol'], eqmd['div_yield'])
        tg_eq = np.linspace(0, o_expiry, 41)
        S = gbm.simulate(tg_eq, int(min(n_paths, 4000)), ois_curve, seed=42)
        mtm_eq = gbm.option_mtm_paths(S, tg_eq, ois_curve, o_strike, o_expiry, units,
                                      call=(o_type == "Call"), smile=smile)
        em = gbm.exposure_metrics(mtm_eq, tg_eq)
        fige = go.Figure()
        fige.add_trace(go.Scatter(x=tg_eq, y=em['PFE'] / 1e7, name='PFE 95%', mode='lines',
                                  line=dict(color=COLORS['PFE'], width=2),
                                  hovertemplate='PFE: ₹%{y:.3f} Cr<extra></extra>'))
        fige.add_trace(go.Scatter(x=tg_eq, y=em['EE'] / 1e7, name='EE', mode='lines',
                                  line=dict(color=COLORS['EE'], width=2.5), fill='tozeroy',
                                  fillcolor='rgba(0,170,255,0.06)',
                                  hovertemplate='EE: ₹%{y:.3f} Cr<extra></extra>'))
        _apply_bbg_chart(fige, f'{eq_index} OPTION EXPOSURE (₹ CR)')
        fige.update_xaxes(title_text='TIME (YEARS)')
        fige.update_yaxes(title_text='EXPOSURE (₹ CR)')
        st.plotly_chart(fige, use_container_width=True)


elif page == "Hybrid Cross-Asset XVA":
    st.markdown("# Hybrid Cross-Asset XVA")
    st.markdown("<div style='color:#8899aa;font-size:0.72rem;margin-bottom:8px'>"
                "MIXED RATES + EQUITY NETTING SET — JOINT SIMULATION — CROSS-ASSET DIVERSIFICATION</div>",
                unsafe_allow_html=True)
    export_strip()

    from src.pricing.equity_options import EquityVolSmile
    from src.xva.hybrid_xva import HybridXVAEngine

    section_header("NETTING SET — IRS + EQUITY LEG",
                   "One counterparty netting set holding an interest-rate swap and an equity index "
                   "trade, valued under a single joint (rate, equity) simulation.")
    hc = st.columns(4)
    h_swap_ntl = hc[0].number_input("IRS NOTIONAL (₹ CR)", value=500.0, step=50.0)
    h_eq_ntl = hc[1].number_input("EQUITY NOTIONAL (₹ CR)", value=300.0, step=50.0)
    h_eq_dir = hc[2].selectbox("EQUITY LEG", ["Short Forward", "Long Forward", "Long Call", "Long Put"])
    h_corr = hc[3].slider("EQUITY-RATE CORR (ρ)", -0.8, 0.8, -0.15, 0.05)

    eqmd = cached_equity_market_data('NIFTY')
    smile = EquityVolSmile.from_chain(
        cached_nifty_option_chain('NIFTY', eqmd['spot'], eqmd['atm_vol']), eqmd['atm_vol'])
    eng = HybridXVAEngine(ois_curve, eqmd['spot'], eqmd['atm_vol'], eqmd['div_yield'],
                          a=mean_rev, sigma_r=vol, equity_rate_corr=h_corr, smile=smile)
    tg_h = np.linspace(0, float(maturity), max(13, int(maturity * 8) + 1))

    with st.spinner("RUNNING JOINT (RATE, EQUITY) SIMULATION..."):
        sim = eng.simulate_joint(tg_h, int(min(n_paths, 6000)), seed=42)
        swap = eng.swap_mtm(sim, h_swap_ntl, fixed_rate, float(maturity), payer=(direction == "Pay Fixed"))
        units = int(h_eq_ntl * 1e7 / eqmd['spot'])
        if h_eq_dir in ("Short Forward", "Long Forward"):
            eq_rs = eng.eq.forward_mtm_paths(sim['spot'], tg_h, ois_curve, eqmd['spot'],
                                             float(maturity), units, long=(h_eq_dir == "Long Forward"))
        else:
            eq_rs = eng.equity_option_mtm(sim, eqmd['spot'], float(maturity), units,
                                          call=(h_eq_dir == "Long Call"))
        eq_cr = eq_rs / 1e7
        res = eng.compute_hybrid_xva(sim, [swap, eq_cr], credit_curve,
                                     funding_spread_bps=cpty_row['funding_spread_bps'])

    section_header("CROSS-ASSET DIVERSIFICATION")
    dc = st.columns(4)
    dc[0].metric("Σ STANDALONE CVA", f"₹{res['sum_standalone_cva']:.4f} CR", accent="amber")
    dc[1].metric("HYBRID (NETTED) CVA", f"₹{res['CVA_hybrid']:.4f} CR", accent="red")
    dc[2].metric("DIVERSIFICATION", f"₹{res['diversification_benefit_cva']:.4f} CR", accent="green")
    dc[3].metric("NETTING BENEFIT", f"{res['netting_benefit_pct']:.1f}%", accent="green")

    dc2 = st.columns(4)
    dc2[0].metric("CVA (IRS LEG)", f"₹{res['standalone_cva'][0]:.4f} CR", accent="blue")
    dc2[1].metric("CVA (EQUITY LEG)", f"₹{res['standalone_cva'][1]:.4f} CR", accent="blue")
    dc2[2].metric("HYBRID DVA", f"₹{res['DVA_hybrid']:.4f} CR", accent="green")
    dc2[3].metric("HYBRID FVA", f"₹{res['FVA_hybrid']:.4f} CR", accent="amber")

    section_header("NETTED vs STANDALONE EXPOSURE")
    figh = go.Figure()
    figh.add_trace(go.Scatter(x=tg_h, y=res['standalone_EE'][0], name='IRS EE (STANDALONE)',
                              mode='lines', line=dict(color=COLORS['EE'], width=1.5, dash='dash'),
                              hovertemplate='IRS EE: ₹%{y:.3f} Cr<extra></extra>'))
    figh.add_trace(go.Scatter(x=tg_h, y=res['standalone_EE'][1], name='EQUITY EE (STANDALONE)',
                              mode='lines', line=dict(color=COLORS['EPE'], width=1.5, dash='dash'),
                              hovertemplate='Equity EE: ₹%{y:.3f} Cr<extra></extra>'))
    figh.add_trace(go.Scatter(x=tg_h, y=res['standalone_EE'][0] + res['standalone_EE'][1],
                              name='SUM (NO NETTING)', mode='lines',
                              line=dict(color='#8899aa', width=1.5, dash='dot'),
                              hovertemplate='Sum EE: ₹%{y:.3f} Cr<extra></extra>'))
    figh.add_trace(go.Scatter(x=tg_h, y=res['EE_netted'], name='NETTED EE (HYBRID)',
                              mode='lines', line=dict(color=COLORS['ENE'], width=3),
                              fill='tozeroy', fillcolor='rgba(0,204,102,0.06)',
                              hovertemplate='Netted EE: ₹%{y:.3f} Cr<extra></extra>'))
    _apply_bbg_chart(figh, 'CROSS-ASSET NETTING — HYBRID EE BELOW THE SUM OF STANDALONE')
    figh.update_layout(hovermode='x unified')
    figh.update_xaxes(title_text='TIME (YEARS)')
    figh.update_yaxes(title_text='EXPOSURE (₹ CR)')
    st.plotly_chart(figh, use_container_width=True)

    st.markdown(f"<div class='assumptions-panel'><div class='ap-title'>WHY THIS MATTERS</div>"
                f"<div style='font-size:0.7rem;color:#8899aa;line-height:1.5'>"
                f"A single-asset XVA engine would charge ₹{res['sum_standalone_cva']:.4f} Cr "
                f"(IRS + equity computed separately). Valuing the mixed book under ONE joint "
                f"(rate, equity) simulation captures the cross-asset offset, reducing the CVA to "
                f"₹{res['CVA_hybrid']:.4f} Cr — a {res['netting_benefit_pct']:.1f}% netting benefit "
                f"that varies with the equity-rate correlation (ρ={h_corr:+.2f}). This is the "
                f"capability that distinguishes a multi-asset XVA engine from asset-by-asset "
                f"calculators.</div></div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# Bind each page's captured charts / tables / metrics to its CSV/PDF buttons.
# ─────────────────────────────────────────────────────────────
flush_export()
