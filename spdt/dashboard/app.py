"""SPDT equity-structuring desk blotter (L14).

A front-office screen organised by the desk's workflow — Blotter (trader), Risk, P&L Explain,
Model Risk, Stress, and a Structuring / vol-surface bench with a per-trade term-sheet drill-in.
All numbers come pre-computed from :mod:`spdt.dashboard.desk_data`; this module is presentation
only. Run with::

    streamlit run spdt/dashboard/app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from spdt.dashboard import theme
from spdt.dashboard.desk_data import load_or_build
from spdt.products import Autocallable, TermSheet
from spdt.reporting import PricingSummary, maturity_scenarios, render_term_sheet

st.set_page_config(page_title="SPDT · Structuring Desk", layout="wide", page_icon="◆")
st.markdown(theme.CSS, unsafe_allow_html=True)


@st.cache_data(show_spinner="Marking the book…")
def _desk() -> dict:
    return load_or_build().payload


D = _desk()
SPOT = D["spot"]


# --- header -----------------------------------------------------------------------------

def _masthead() -> None:
    m = D["model"]
    mv = D["market_move"]
    st.markdown(
        f'<div class="masthead">'
        f'<div class="desk">SPDT <span class="accent">//</span> EQUITY STRUCTURING DESK</div>'
        f'<div class="meta">{D["underlying"]} · spot {SPOT:,.0f} · as of {D["as_of"]}<br>'
        f'ATM vol {m["atm_vol"]*100:.1f}% · r {m["r"]*100:.2f}% · q {m["q"]*100:.2f}% · '
        f'surface {"arb-free" if D["arb_clean"] else "FLAGGED"} · '
        f'P&L move +{mv["spot_bp"]}bp spot / +{mv["vol_pt"]}vol</div></div>',
        unsafe_allow_html=True,
    )


def _kpis() -> None:
    g = D["net_greeks"]
    cash_delta = g["delta"] * SPOT * 0.01           # P&L per +1% spot
    vega_pt = g["vega"] / 100.0                      # P&L per +1 vol point
    cols = st.columns(6)
    tiles = [
        theme.kpi("Book NAV", f"{D['nav']:,.0f}", f"{len(D['positions'])} notes"),
        theme.kpi("Overnight P&L", f"{D['day_pnl']:+,.2f}", "Taylor explain",
                  "pos" if D["day_pnl"] >= 0 else "neg"),
        theme.kpi("Net Δ", f"{cash_delta:+,.2f}", "per +1% spot",
                  "pos" if cash_delta >= 0 else "neg"),
        theme.kpi("Net Vega", f"{vega_pt:+,.2f}", "per +1 vol pt",
                  "pos" if vega_pt >= 0 else "neg"),
        theme.kpi("Model reserve", f"{D['total_reserve']:,.2f}", "bid-offer", "accent"),
        theme.kpi("Worst stress", f"{min(s['pnl'] for s in D['stress']):,.0f}",
                  "equity crash", "neg"),
    ]
    for col, html in zip(cols, tiles):
        col.markdown(html, unsafe_allow_html=True)


# --- views ------------------------------------------------------------------------------

def _blotter() -> None:
    st.markdown('<div class="section">Position blotter</div>', unsafe_allow_html=True)
    df = pd.DataFrame(D["positions"])
    df["cash_delta"] = df["delta"] * SPOT * 0.01
    df["vega_pt"] = df["vega"] / 100.0
    view = df[["trade_id", "maturity", "coupon", "autocall", "coupon_barrier", "knock_in",
               "memory", "pv", "cash_delta", "vega_pt", "day_pnl"]]
    st.dataframe(
        view, use_container_width=True, hide_index=True, height=460,
        column_config={
            "trade_id": "Trade",
            "maturity": st.column_config.NumberColumn("Mat (y)", format="%.1f"),
            "coupon": st.column_config.NumberColumn("Cpn", format="%.3f"),
            "autocall": st.column_config.NumberColumn("AC", format="%.2f"),
            "coupon_barrier": st.column_config.NumberColumn("CB", format="%.2f"),
            "knock_in": st.column_config.NumberColumn("KI", format="%.2f"),
            "memory": st.column_config.CheckboxColumn("Mem"),
            "pv": st.column_config.NumberColumn("PV", format="%.2f"),
            "cash_delta": st.column_config.NumberColumn("Δ /1%", format="%.2f"),
            "vega_pt": st.column_config.NumberColumn("ν /pt", format="%.2f"),
            "day_pnl": st.column_config.NumberColumn("Day P&L", format="%.3f"),
        },
    )


def _risk() -> None:
    left, right = st.columns([3, 2])
    with left:
        st.markdown('<div class="section">Vega ladder by tenor</div>', unsafe_allow_html=True)
        ladder = D["vega_ladder"]
        fig = go.Figure(go.Bar(x=list(ladder), y=[v / 100.0 for v in ladder.values()],
                               marker_color=theme.ACCENT_2))
        theme.style(fig, height=320,
                          yaxis_title="vega / vol pt", xaxis_title="maturity bucket")
        st.plotly_chart(fig, use_container_width=True, theme=None)
    with right:
        st.markdown('<div class="section">Gamma concentration</div>', unsafe_allow_html=True)
        df = pd.DataFrame(D["positions"]).sort_values("gamma")
        fig = go.Figure(go.Bar(x=df["gamma"], y=df["trade_id"], orientation="h",
                               marker_color=theme.DOWN))
        theme.style(fig, height=320, xaxis_title="gamma")
        st.plotly_chart(fig, use_container_width=True, theme=None)
    g = D["net_greeks"]
    st.markdown(
        f'<span class="stChip">net Δ {g["delta"]:.4f}</span> '
        f'<span class="stChip">net Γ {g["gamma"]:.5f}</span> '
        f'<span class="stChip">net ν {g["vega"]:.1f}</span> '
        f'<span class="stChip">net ρ {g["rho"]:.1f}</span>',
        unsafe_allow_html=True,
    )


def _pnl_explain() -> None:
    st.markdown('<div class="section">Overnight P&L attribution</div>', unsafe_allow_html=True)
    e = D["pnl_explain"]
    order = [("Delta", "delta_pnl"), ("Gamma", "gamma_pnl"), ("Theta", "theta_pnl"),
             ("Vega", "vega_pnl"), ("Volga", "volga_pnl"), ("Vanna", "vanna_pnl"),
             ("Rho", "rho_pnl"), ("Residual", "residual")]
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=["relative"] * len(order) + ["total"],
        x=[label for label, _ in order] + ["Total"],
        y=[e[key] for _, key in order] + [e["total"]],
        connector={"line": {"color": theme.BORDER}},
        increasing={"marker": {"color": theme.UP}},
        decreasing={"marker": {"color": theme.DOWN}},
        totals={"marker": {"color": theme.ACCENT}},
    ))
    theme.style(fig, height=380, yaxis_title="P&L")
    st.plotly_chart(fig, use_container_width=True, theme=None)
    st.caption(
        f"Residual {e['residual']:+.4f} of {e['total']:+.4f} total — "
        "small residual ⇒ Greeks and full revaluation agree."
    )


def _model_risk() -> None:
    st.markdown('<div class="section">Model reserves (bid-offer)</div>', unsafe_allow_html=True)
    df = pd.DataFrame(D["reserves"]).sort_values("bid_offer", ascending=False)
    col1, col2 = st.columns([2, 3])
    with col1:
        st.dataframe(
            df, use_container_width=True, hide_index=True, height=360,
            column_config={"trade_id": "Trade",
                           "bid_offer": st.column_config.NumberColumn("Reserve", format="%.3f")})
    with col2:
        fig = go.Figure(go.Bar(x=df["bid_offer"], y=df["trade_id"], orientation="h",
                               marker_color=theme.ACCENT))
        theme.style(fig, height=360, xaxis_title="reserve")
        st.plotly_chart(fig, use_container_width=True, theme=None)
    st.caption(
        f"Total reserve held: {D['total_reserve']:.2f}. LSV−LV reserve available per trade."
    )


def _stress() -> None:
    st.markdown('<div class="section">Coherent stress scenarios</div>', unsafe_allow_html=True)
    s = sorted(D["stress"], key=lambda x: x["pnl"])
    colors = [theme.DOWN if x["pnl"] < 0 else theme.UP for x in s]
    fig = go.Figure(go.Bar(x=[x["pnl"] for x in s], y=[x["scenario"] for x in s],
                           orientation="h", marker_color=colors,
                           text=[f"{x['pct']:+.1f}%" for x in s], textposition="outside"))
    theme.style(fig, height=320, xaxis_title="book P&L")
    st.plotly_chart(fig, use_container_width=True, theme=None)
    st.caption("Scenarios are multi-factor: a crash also spikes vol — not a one-factor bump.")


def _structuring() -> None:
    left, right = st.columns([3, 2])
    with left:
        st.markdown('<div class="section">Implied-vol surface</div>', unsafe_allow_html=True)
        s = D["surface"]
        fig = go.Figure(go.Heatmap(z=s["iv"], x=s["log_moneyness"], y=s["tenors"],
                                   colorscale="Cividis", colorbar={"title": "IV %"}))
        theme.style(fig, height=380,
                          xaxis_title="log-moneyness", yaxis_title="tenor (y)")
        st.plotly_chart(fig, use_container_width=True, theme=None)
    with right:
        st.markdown('<div class="section">Term-sheet drill-in</div>', unsafe_allow_html=True)
        ids = [p["trade_id"] for p in D["positions"]]
        chosen = st.selectbox("Trade", ids, label_visibility="collapsed")
        pos = next(p for p in D["positions"] if p["trade_id"] == chosen)
        ts = TermSheet(
            "autocallable", (pos["underlying"],), pos["notional"],
            tuple(pos["observation_times"]),
            {"coupon_rate": pos["coupon"], "autocall_level": pos["autocall"],
             "coupon_barrier": pos["coupon_barrier"], "knock_in": pos["knock_in"],
             "memory": pos["memory"]})
        scenarios = maturity_scenarios(_note(pos), (0.4, 0.6, 0.8, 1.0, 1.2))
        st.markdown(render_term_sheet(ts, PricingSummary(pos["pv"]), scenarios))


def _note(pos: dict) -> Autocallable:
    return Autocallable(
        notional=pos["notional"], observation_times=tuple(pos["observation_times"]),
        coupon_rate=pos["coupon"], autocall_level=pos["autocall"],
        coupon_barrier=pos["coupon_barrier"], knock_in=pos["knock_in"],
        memory=pos["memory"], initial_fixing=SPOT)


# --- layout -----------------------------------------------------------------------------

_masthead()
_kpis()
st.write("")
_tabs = st.tabs(["BLOTTER", "RISK", "P&L EXPLAIN", "MODEL RISK", "STRESS", "STRUCTURING"])
for _tab, _view in zip(
    _tabs, (_blotter, _risk, _pnl_explain, _model_risk, _stress, _structuring)
):
    with _tab:
        _view()
