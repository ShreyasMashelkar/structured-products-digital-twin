"""Visual language for the desk blotter — one place for colour, type, and chart styling.

A trading screen, not a homework plot: a near-black canvas, a restrained ink palette, a single
amber accent, tabular numerals, and tight spacing. Greens/reds are reserved strictly for P&L
sign. Keeping every colour and the Plotly template here means the views stay consistent and the
look can be retuned in one file.
"""

from __future__ import annotations

import plotly.graph_objects as go

# --- palette -----------------------------------------------------------------------------
# (palette constants below)
BG = "#0b0e14"          # canvas
PANEL = "#11161f"       # cards / panels
PANEL_2 = "#161c28"     # raised rows
BORDER = "#222b3a"
INK = "#e6edf3"         # primary text
MUTED = "#8b97a7"       # secondary text
ACCENT = "#e0a430"      # amber — the desk accent
ACCENT_2 = "#3aa6b9"    # teal — secondary series
UP = "#3fb950"          # P&L positive
DOWN = "#f0556b"        # P&L negative
GRID = "#1b2330"

FONT = "ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, monospace"


def style(fig: go.Figure, **overrides: object) -> go.Figure:
    """Apply the dark, chartjunk-free blotter styling directly to a figure.

    Set on the layout itself (not via a Template object), which Streamlit's renderer applies
    reliably when charts are drawn with ``theme=None``.
    """
    fig.update_layout(
        paper_bgcolor=PANEL,
        plot_bgcolor=PANEL,
        font={"family": FONT, "color": INK, "size": 12},
        colorway=[ACCENT, ACCENT_2, UP, DOWN, MUTED],
        margin={"l": 52, "r": 20, "t": 28, "b": 40},
        legend={"bgcolor": "rgba(0,0,0,0)", "font": {"color": MUTED}},
        hoverlabel={"bgcolor": PANEL_2, "font": {"family": FONT, "color": INK}},
        **overrides,
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=BORDER, linecolor=BORDER, color=MUTED)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=BORDER, linecolor=BORDER, color=MUTED)
    return fig


CSS = f"""
<style>
  .stApp {{ background: {BG}; }}
  html, body, [class*="css"] {{ font-family: {FONT}; color: {INK}; }}
  #MainMenu, footer, header {{ visibility: hidden; }}
  .block-container {{ padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1500px; }}

  /* masthead */
  .masthead {{
    display: flex; align-items: baseline; justify-content: space-between;
    border-bottom: 1px solid {BORDER}; padding-bottom: .6rem; margin-bottom: 1rem;
  }}
  .masthead .desk {{ font-size: 1.35rem; font-weight: 700; letter-spacing: .04em; color: {INK}; }}
  .masthead .desk .accent {{ color: {ACCENT}; }}
  .masthead .meta {{ font-size: .78rem; color: {MUTED}; text-align: right; line-height: 1.4; }}

  /* KPI tiles */
  .kpi {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: .7rem .9rem; height: 100%;
  }}
  .kpi .label {{ font-size: .68rem; color: {MUTED}; text-transform: uppercase;
                letter-spacing: .08em; }}
  .kpi .value {{ font-size: 1.35rem; font-weight: 700; color: {INK}; margin-top: .15rem; }}
  .kpi .sub {{ font-size: .72rem; color: {MUTED}; margin-top: .1rem; }}
  .pos {{ color: {UP}; }} .neg {{ color: {DOWN}; }} .accent {{ color: {ACCENT}; }}

  /* section headers */
  .section {{
    font-size: .8rem; color: {MUTED}; text-transform: uppercase; letter-spacing: .1em;
    border-left: 3px solid {ACCENT}; padding-left: .55rem; margin: .4rem 0 .7rem;
  }}

  /* tabs */
  .stTabs [data-baseweb="tab-list"] {{ gap: .2rem; border-bottom: 1px solid {BORDER}; }}
  .stTabs [data-baseweb="tab"] {{
    background: transparent; color: {MUTED}; font-size: .82rem; letter-spacing: .03em;
    padding: .4rem .9rem;
  }}
  .stTabs [aria-selected="true"] {{ color: {INK}; border-bottom: 2px solid {ACCENT}; }}

  /* dataframes: dense, tabular */
  [data-testid="stDataFrame"] {{ border: 1px solid {BORDER}; border-radius: 8px; }}
  .stChip {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 999px;
            padding: .1rem .55rem; font-size: .72rem; color: {MUTED}; }}
</style>
"""


def kpi(label: str, value: str, sub: str = "", tone: str = "") -> str:
    """Render one KPI tile as HTML (tone ∈ {'', 'pos', 'neg', 'accent'})."""
    cls = f" {tone}" if tone else ""
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return (
        f'<div class="kpi"><div class="label">{label}</div>'
        f'<div class="value{cls}">{value}</div>{sub_html}</div>'
    )


def signed(value: float, fmt: str = ",.0f") -> str:
    """Format a number with an explicit sign and a P&L colour class span."""
    cls = "pos" if value >= 0 else "neg"
    return f'<span class="{cls}">{value:+{fmt}}</span>'
