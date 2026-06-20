"""SPDT equity-structuring desk blotter (L14).

A front-office screen organised by the desk's workflow — Blotter (trader), Risk, P&L Explain,
Model Risk, Stress, and a Structuring / vol-surface bench with a per-trade term-sheet drill-in.
All numbers come pre-computed from :mod:`spdt.dashboard.desk_data`; this module is presentation
only. Run with::

    streamlit run spdt/dashboard/app.py
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from spdt.dashboard import theme
from spdt.dashboard.desk_data import load_or_build
from spdt.pricing import BlackScholes, price_mc
from spdt.products import Autocallable, TermSheet
from spdt.reporting import PricingSummary, maturity_scenarios, render_term_sheet
from spdt.structurer import ClientBrief, par_target, propose_autocallable, solve_to_par

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
        f'<div><span class="desk">SPDT <span class="accent">//</span> Structuring Desk</span>'
        f'<span class="tag">live</span></div>'
        f'<div class="meta">'
        f'{D["underlying"]} · spot <b>{SPOT:,.0f}</b> · {D["as_of"]}<br>'
        f'ATM vol <b>{m["atm_vol"]*100:.1f}%</b> · r <b>{m["r"]*100:.2f}%</b> · '
        f'q <b>{m["q"]*100:.2f}%</b> · funding <b>+{D.get("funding_spread_bp", 0)}bp</b><br>'
        f'surface <b>{"arb-free" if D["arb_clean"] else "FLAGGED"}</b> · '
        f'overnight move +{mv["spot_bp"]}bp spot / +{mv["vol_pt"]} vol</div></div>',
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
        theme.kpi("Model reserve", f"{D.get('total_model_reserve', 0.0):,.2f}", "LSV−LV", "accent"),
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
                               marker_color=theme.TEAL))
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
    st.markdown('<div class="section">Model reserves — LSV−LV and bid-offer</div>',
                unsafe_allow_html=True)
    df = pd.DataFrame(D["reserves"]).sort_values("lsv_minus_lv", ascending=False)
    col1, col2 = st.columns([2, 3])
    with col1:
        view = df[["trade_id", "lv_pv", "lsv_pv", "lsv_minus_lv", "bid_offer"]]
        st.dataframe(
            view, use_container_width=True, hide_index=True, height=360,
            column_config={
                "trade_id": "Trade",
                "lv_pv": st.column_config.NumberColumn("LV PV", format="%.2f"),
                "lsv_pv": st.column_config.NumberColumn("LSV PV", format="%.2f"),
                "lsv_minus_lv": st.column_config.NumberColumn("LSV−LV", format="%.3f"),
                "bid_offer": st.column_config.NumberColumn("Bid-offer", format="%.3f"),
            })
    with col2:
        fig = go.Figure()
        fig.add_bar(x=df["lsv_minus_lv"], y=df["trade_id"], orientation="h",
                    marker_color=theme.ACCENT, name="LSV−LV model reserve")
        fig.add_bar(x=df["bid_offer"], y=df["trade_id"], orientation="h",
                    marker_color=theme.TEAL, name="bid-offer reserve")
        theme.style(fig, height=360, xaxis_title="reserve")
        fig.update_layout(barmode="group", legend={"orientation": "h", "y": 1.1})
        st.plotly_chart(fig, use_container_width=True, theme=None)
    st.caption(
        f"Total LSV−LV model reserve {D['total_model_reserve']:.2f} · total bid-offer "
        f"{D['total_reserve']:.2f}. LV and LSV agree on vanillas (same marginals) but disagree "
        "on the autocallable's forward-smile dynamics — that gap is the model reserve."
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


def _note(pos: dict) -> Autocallable:
    return Autocallable(
        notional=pos["notional"], observation_times=tuple(pos["observation_times"]),
        coupon_rate=pos["coupon"], autocall_level=pos["autocall"],
        coupon_barrier=pos["coupon_barrier"], knock_in=pos["knock_in"],
        memory=pos["memory"], initial_fixing=SPOT)


@st.cache_data(show_spinner="Solving the structure to par…")
def _solve_structure(target_coupon: float, max_downside: float, maturity: float, obs_py: int):
    """Client brief → proposed Phoenix → solve the coupon to par (live L6 origination)."""
    brief = ClientBrief(target_coupon, max_downside, maturity, obs_py)
    ts = propose_autocallable(brief)
    m = D["model"]
    model = BlackScholes(spot=SPOT, r=m["r"], q=m["q"], sigma=m["atm_vol"])

    def pv_of_coupon(c: float) -> float:
        note = dataclasses.replace(
            Autocallable.from_termsheet(ts, initial_fixing=SPOT), coupon_rate=c
        )
        return price_mc(note, model, n_paths=15_000, seed=7).price

    curve = [(c, pv_of_coupon(c)) for c in [0.0025 * i for i in range(1, 19)]]
    try:
        solved = solve_to_par(pv_of_coupon, par_target(100.0, fee=1.0), (0.0, 0.06))
        solved_period, solved_pv = solved.param, solved.achieved_pv
    except ValueError:
        solved_period, solved_pv = None, None
    return ts.params, curve, solved_period, solved_pv


def _structuring() -> None:
    st.markdown('<div class="section">Client brief → proposed structure → solve to par</div>',
                unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    target = c1.slider("Target annual coupon", 0.04, 0.20, 0.12, 0.01, format="%.0f%%",
                       help="What the client asks for")
    downside = c2.slider("Downside they can stomach", 0.10, 0.50, 0.30, 0.05, format="%.0f%%")
    maturity = c3.selectbox("Maturity (years)", (1.0, 2.0, 3.0), index=0)
    obs_py = c4.selectbox("Observations / year", (2, 4, 12), index=1)

    params, curve, solved_period, solved_pv = _solve_structure(target, downside, maturity, obs_py)
    indic_period = params["coupon_rate"]
    ki = params["knock_in"]

    left, right = st.columns([2, 3])
    with left:
        st.markdown(
            f'<span class="stChip">proposed: Phoenix autocallable</span> '
            f'<span class="stChip">knock-in {ki*100:.0f}%</span> '
            f'<span class="stChip">memory coupon</span>',
            unsafe_allow_html=True,
        )
        if solved_period is not None:
            st.metric("Solved coupon (to par, 1.00 fee)",
                      f"{solved_period * obs_py * 100:.2f}% p.a.",
                      f"{(solved_period - indic_period) * obs_py * 100:+.2f}% vs indicative")
            st.caption(
                f"At {ki*100:.0f}% knock-in the fair annual coupon is "
                f"{solved_period * obs_py * 100:.2f}% (PV {solved_pv:.2f} = 100 − 1.00 fee). "
                f"The client's {target*100:.0f}% ask "
                + ("is achievable." if solved_period * obs_py >= target
                   else "would need a lower knock-in or more downside sold.")
            )
        else:
            st.warning("No coupon in range prices this structure to par — adjust the knock-in.")
    with right:
        cs = [c * obs_py * 100 for c, _ in curve]
        fig = go.Figure(go.Scatter(
            x=cs, y=[pv for _, pv in curve], mode="lines+markers",
            line={"color": theme.TEAL, "width": 2.5, "shape": "spline"},
            marker={"size": 5, "color": theme.TEAL},
            fill="tozeroy", fillcolor="rgba(79,195,215,.08)",
            hovertemplate="coupon %{x:.2f}%% · PV %{y:.2f}<extra></extra>"))
        fig.add_hline(y=99.0, line_dash="dash", line_color=theme.ACCENT,
                      annotation_text="par − fee", annotation_font_color=theme.ACCENT)
        if solved_period is not None:
            fig.add_vline(x=solved_period * obs_py * 100, line_dash="dot", line_color=theme.UP,
                          annotation_text="solved", annotation_font_color=theme.UP)
        lo = min(pv for _, pv in curve)
        theme.style(fig, height=300, xaxis_title="annual coupon (%)", yaxis_title="model PV",
                    yaxis_range=[lo - 0.5, max(pv for _, pv in curve) + 0.5], hovermode="x")
        st.plotly_chart(fig, use_container_width=True, theme=None)

    st.markdown('<div class="section">Income / protection catalog — two-curve discounting</div>',
                unsafe_allow_html=True)
    cat = pd.DataFrame(D["catalog"])
    st.dataframe(
        cat[["name", "pv_two_curve", "pv_ois_only", "funding_impact"]],
        use_container_width=True, hide_index=True,
        column_config={
            "name": "Structure",
            "pv_two_curve": st.column_config.NumberColumn("PV (OIS + funding)", format="%.3f"),
            "pv_ois_only": st.column_config.NumberColumn("PV (OIS only)", format="%.3f"),
            "funding_impact": st.column_config.NumberColumn("Funding impact", format="%.3f"),
        })
    st.caption(
        f"The issuer funding spread (+{D.get('funding_spread_bp', 0)}bp over OIS) discounts each "
        "note's bond leg, lowering PV — the cost decomposition a structurer prices. BRC / reverse "
        "convertible / capital-protected note shown alongside the autocallable book."
    )

    st.markdown('<div class="section">Implied-vol surface · SSVI (arb-free)</div>',
                unsafe_allow_html=True)
    s = D["surface"]
    fig = go.Figure(go.Surface(
        z=s["iv"], x=s["log_moneyness"], y=s["tenors"],
        colorscale=theme.SURFACE_SCALE,
        colorbar={"title": {"text": "IV %", "font": {"color": theme.MUTED, "size": 11}},
                  "thickness": 12, "len": 0.65, "outlinewidth": 0,
                  "tickfont": {"family": theme.MONO, "size": 9, "color": theme.MUTED}},
        contours={"z": {"show": True, "usecolormap": True, "highlightcolor": theme.INK,
                        "width": 1, "project": {"z": True}}},
        lighting={"ambient": 0.78, "diffuse": 0.6, "specular": 0.12, "roughness": 0.92},
        hovertemplate="k %{x:.2f} · T %{y:.2f}y · IV %{z:.1f}%<extra></extra>",
    ))
    theme.style_surface(fig, height=480)
    st.plotly_chart(fig, use_container_width=True, theme=None)


def _drill_in() -> None:
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


def _hedging() -> None:
    st.markdown('<div class="section">Dynamic delta-hedge replication error</div>',
                unsafe_allow_html=True)
    h = D["hedging"]
    left, right = st.columns([3, 2])
    with left:
        fig = go.Figure(go.Scatter(
            x=[r["n_steps"] for r in h], y=[r["std_pnl"] for r in h],
            mode="lines+markers", line={"color": theme.DOWN, "width": 2.5, "shape": "spline"},
            marker={"size": 6, "color": theme.DOWN}, fill="tozeroy",
            fillcolor="rgba(251,106,130,.10)",
            hovertemplate="%{x} rebalances · std %{y:.1f}<extra></extra>"))
        theme.style(fig, height=320, xaxis_title="rebalances over the option's life",
                    yaxis_title="hedging P&L std", hovermode="x")
        fig.update_xaxes(type="log")
        st.plotly_chart(fig, use_container_width=True, theme=None)
    with right:
        fig = go.Figure(go.Bar(
            x=[str(r["n_steps"]) for r in h], y=[r["slippage_cost"] for r in h],
            marker_color=theme.ACCENT, marker_line_width=0,
            hovertemplate="%{x} rebalances · cost %{y:.1f}<extra></extra>"))
        theme.style(fig, height=320, xaxis_title="rebalances",
                    yaxis_title="mean slippage cost (2bp)", hovermode="closest")
        st.plotly_chart(fig, use_container_width=True, theme=None)
    st.caption(
        "Hedging-P&L standard deviation falls roughly as 1/√(rebalances) — the classic "
        "Black-Scholes-Merton discrete-replication error — while transaction-cost slippage "
        "rises with trading frequency: the trader's gamma-vs-cost trade-off."
    )


def _backtest() -> None:
    b = D["backtest"]
    cols = st.columns(5)
    cols[0].markdown(theme.kpi("Autocall rate", f"{b['autocall_rate']*100:.0f}%",
                               f"{b['n_issuances']} issuances"), unsafe_allow_html=True)
    cols[1].markdown(theme.kpi("Mean return", f"{b['mean_total_return']*100:.1f}%",
                               "of notional"), unsafe_allow_html=True)
    cols[2].markdown(theme.kpi("Loss rate", f"{b['loss_rate']*100:.0f}%", "capital loss",
                               "neg" if b["loss_rate"] > 0 else "pos"), unsafe_allow_html=True)
    cols[3].markdown(theme.kpi("Mean loss", f"{b['mean_capital_loss']:.1f}", "when lost", "neg"),
                     unsafe_allow_html=True)
    cols[4].markdown(theme.kpi("Worst 5%", f"{b['worst_5pct_return']*100:.0f}%", "tail return",
                               "neg"), unsafe_allow_html=True)
    st.write("")
    left, right = st.columns([3, 2])
    with left:
        st.markdown('<div class="section">Per-issuance return distribution</div>',
                    unsafe_allow_html=True)
        fig = go.Figure(go.Histogram(x=b["returns"], nbinsx=40, marker_color=theme.TEAL,
                                     marker_line_width=0, opacity=0.9))
        fig.add_vline(x=b["worst_5pct_return"], line_dash="dot", line_color=theme.DOWN,
                      annotation_text="worst 5%", annotation_font_color=theme.DOWN)
        theme.style(fig, height=300, xaxis_title="total return (× notional)", yaxis_title="count",
                    hovermode="closest", bargap=0.05)
        st.plotly_chart(fig, use_container_width=True, theme=None)
    with right:
        st.markdown('<div class="section">Realised underlying (10y)</div>', unsafe_allow_html=True)
        fig = go.Figure(go.Scatter(y=b["series"], mode="lines",
                                   line={"color": theme.ACCENT, "width": 2},
                                   fill="tozeroy", fillcolor="rgba(230,179,74,.07)",
                                   hovertemplate="month %{x} · %{y:,.0f}<extra></extra>"))
        theme.style(fig, height=300, xaxis_title="month", yaxis_title="level", hovermode="x")
        st.plotly_chart(fig, use_container_width=True, theme=None)
    st.caption(
        "Rolling monthly Phoenix issuance on the *realised* path (real-world drift, not "
        "risk-neutral). Autocallables 'look great until they don't': a high autocall rate and "
        "tidy mean, with the character living in the worst-5% tail."
    )


# --- layout -----------------------------------------------------------------------------

def _book() -> None:
    _blotter()
    _drill_in()


_masthead()
_kpis()
st.write("")
# Tabs follow the desk's workflow: structure → book → risk → P&L → hedge → model val →
# stress → history.
_tabs = st.tabs(
    ["STRUCTURING", "BLOTTER", "RISK", "P&L EXPLAIN", "HEDGING", "MODEL RISK", "STRESS", "BACKTEST"]
)
for _tab, _view in zip(
    _tabs,
    (_structuring, _book, _risk, _pnl_explain, _hedging, _model_risk, _stress, _backtest),
):
    with _tab:
        _view()
