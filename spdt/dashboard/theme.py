"""Visual language for the desk — one place for colour, type, and chart styling.

A modern front-office terminal: a deep, slightly-cool canvas with layered panels, a refined
gold accent, a clean sans (Inter) for chrome and tabular monospace (JetBrains Mono) reserved for
numerals. Greens/reds mean P&L sign and nothing else. Every colour, the Plotly look for 2-D and
3-D charts, and the component CSS live here so the views stay consistent and the whole skin can
be retuned in one file.
"""

from __future__ import annotations

import plotly.graph_objects as go

# --- palette -----------------------------------------------------------------------------
BG = "#090B10"          # app canvas
BG_2 = "#0C0F16"        # gradient partner for depth
PANEL = "#12161F"       # cards / panels
PANEL_2 = "#171C27"     # raised rows / hover
BORDER = "#232A37"      # panel borders
BORDER_SOFT = "#1A202B"  # faint dividers
INK = "#EAEEF5"         # primary text
MUTED = "#97A2B4"       # secondary text
FAINT = "#5B6678"       # tertiary text
ACCENT = "#E6B34A"      # gold — the desk accent
ACCENT_SOFT = "#3a2f1c"  # gold wash for fills
TEAL = "#4FC3D7"        # secondary series
VIOLET = "#9D8DF1"      # tertiary series
UP = "#3DD68C"          # P&L positive
DOWN = "#FB6A82"        # P&L negative
GRID = "#19202C"        # chart gridlines

SANS = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace"

# A dark→gold colourscale for the vol surface (cool valleys, warm peaks).
SURFACE_SCALE = [
    [0.0, "#10233A"], [0.25, "#1E5C6E"], [0.5, "#34A0A4"],
    [0.75, "#C9A227"], [1.0, "#F2C14E"],
]


def style(
    fig: go.Figure, *, hovermode: str = "x unified", bargap: float = 0.42, **overrides: object
) -> go.Figure:
    """Apply the dark, chartjunk-free 2-D styling. Numerals render in tabular mono."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": SANS, "color": MUTED, "size": 12},
        colorway=[ACCENT, TEAL, VIOLET, UP, DOWN],
        margin={"l": 54, "r": 18, "t": 30, "b": 42},
        legend={"bgcolor": "rgba(0,0,0,0)", "font": {"color": MUTED, "size": 11},
                "orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        hovermode=hovermode,
        hoverlabel={"bgcolor": PANEL_2, "bordercolor": BORDER,
                    "font": {"family": MONO, "color": INK, "size": 11}},
        bargap=bargap,
        **overrides,
    )
    axis = {"gridcolor": GRID, "griddash": "dot", "zeroline": False, "linecolor": BORDER_SOFT,
            "tickfont": {"family": MONO, "size": 10, "color": MUTED},
            "title_font": {"family": SANS, "size": 11, "color": MUTED}}
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    return fig


def style_surface(fig: go.Figure, **overrides: object) -> go.Figure:
    """Style a 3-D surface scene to match the terminal look."""
    pane = {"backgroundcolor": "rgba(0,0,0,0)", "gridcolor": GRID, "showbackground": True,
            "zerolinecolor": BORDER, "color": MUTED,
            "tickfont": {"family": MONO, "size": 9, "color": MUTED},
            "title_font": {"family": SANS, "size": 11, "color": MUTED}}
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": SANS, "color": MUTED},
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        scene={
            "xaxis": dict(pane, title="log-moneyness"),
            "yaxis": dict(pane, title="tenor (y)"),
            "zaxis": dict(pane, title="implied vol %"),
            "camera": {"eye": {"x": 1.55, "y": -1.65, "z": 0.85}},
            "aspectratio": {"x": 1.1, "y": 1.0, "z": 0.62},
        },
        **overrides,
    )
    return fig


CSS = f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

  .stApp {{
    background:
      radial-gradient(1200px 600px at 78% -8%, rgba(230,179,74,.05), transparent 60%),
      radial-gradient(900px 500px at 5% 0%, rgba(79,195,215,.04), transparent 55%),
      linear-gradient(180deg, {BG_2} 0%, {BG} 60%);
    background-attachment: fixed;
  }}
  html, body, [class*="css"], .stMarkdown, p, span, div {{
    font-family: {SANS}; color: {INK}; -webkit-font-smoothing: antialiased;
  }}
  #MainMenu, footer, header {{ visibility: hidden; }}
  .block-container {{ padding-top: 1.2rem; padding-bottom: 2.5rem; max-width: 1560px; }}
  .stApp [data-testid="stDecoration"] {{ display: none; }}

  /* masthead */
  .masthead {{
    display: flex; align-items: flex-end; justify-content: space-between;
    padding: .2rem 0 1rem; margin-bottom: 1.1rem;
    border-bottom: 1px solid {BORDER_SOFT};
  }}
  .masthead .desk {{
    font-size: 1.5rem; font-weight: 800; letter-spacing: -.01em; color: {INK};
  }}
  .masthead .desk .accent {{ color: {ACCENT}; font-weight: 800; }}
  .masthead .tag {{
    display:inline-block; font-size:.6rem; font-weight:700; letter-spacing:.16em;
    text-transform:uppercase; color:{ACCENT}; border:1px solid {BORDER};
    border-radius:5px; padding:.12rem .45rem; margin-left:.6rem; vertical-align:middle;
    background:{ACCENT_SOFT};
  }}
  .masthead .meta {{
    font-family:{MONO}; font-size:.74rem; color:{MUTED}; text-align:right; line-height:1.7;
  }}
  .masthead .meta b {{ color:{INK}; font-weight:600; }}

  /* KPI tiles */
  div[data-testid="stHorizontalBlock"] {{ gap:.7rem; }}
  .kpi {{
    position:relative; background:linear-gradient(160deg, {PANEL} 0%, {PANEL_2} 130%);
    border:1px solid {BORDER}; border-radius:12px; padding:.85rem 1rem .9rem; height:100%;
    overflow:hidden; transition:transform .12s ease, border-color .12s ease;
  }}
  .kpi:hover {{ transform:translateY(-2px); border-color:{ACCENT}; }}
  .kpi::before {{
    content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:{MUTED};
    opacity:.5;
  }}
  .kpi.k-pos::before {{ background:{UP}; opacity:1; }}
  .kpi.k-neg::before {{ background:{DOWN}; opacity:1; }}
  .kpi.k-accent::before {{ background:{ACCENT}; opacity:1; }}
  .kpi .label {{ font-size:.64rem; color:{MUTED}; text-transform:uppercase; letter-spacing:.12em;
                font-weight:600; }}
  .kpi .value {{ font-family:{MONO}; font-size:1.5rem; font-weight:600; color:{INK};
                margin-top:.28rem; line-height:1; letter-spacing:-.02em; }}
  .kpi .sub {{ font-size:.7rem; color:{MUTED}; margin-top:.35rem; }}
  .pos, .value.pos {{ color:{UP}; }} .neg, .value.neg {{ color:{DOWN}; }}
  .accent, .value.accent {{ color:{ACCENT}; }}

  /* panels around charts */
  [data-testid="stPlotlyChart"] {{
    background:{PANEL}; border:1px solid {BORDER}; border-radius:12px; padding:.5rem .4rem;
  }}

  /* section headers */
  .section {{
    font-size:.72rem; color:{INK}; text-transform:uppercase; letter-spacing:.13em;
    font-weight:700; margin:1.1rem 0 .6rem; display:flex; align-items:center; gap:.5rem;
  }}
  .section::before {{ content:""; width:14px; height:2px; background:{ACCENT}; border-radius:2px; }}

  /* tabs */
  .stTabs [data-baseweb="tab-list"] {{
    gap:.15rem; border-bottom:1px solid {BORDER}; padding-bottom:0;
  }}
  .stTabs [data-baseweb="tab"] {{
    background:transparent; color:{MUTED}; font-size:.76rem; font-weight:600; letter-spacing:.06em;
    padding:.5rem 1rem; border-radius:8px 8px 0 0;
  }}
  .stTabs [data-baseweb="tab"]:hover {{ color:{INK}; background:rgba(255,255,255,.02); }}
  .stTabs [aria-selected="true"] {{ color:{ACCENT}; border-bottom:2px solid {ACCENT}; }}
  .stTabs [data-baseweb="tab-highlight"] {{ background:transparent; }}

  /* dataframes */
  [data-testid="stDataFrame"] {{ border:1px solid {BORDER}; border-radius:12px; overflow:hidden; }}
  [data-testid="stDataFrame"] [role="columnheader"] {{
    background:{PANEL_2} !important; color:{MUTED} !important;
    text-transform:uppercase; font-size:.66rem; letter-spacing:.06em; font-weight:700;
  }}

  /* widgets */
  .stSlider label, .stSelectbox label {{
    color:{MUTED} !important; font-size:.7rem !important; font-weight:600 !important;
    text-transform:uppercase; letter-spacing:.06em;
  }}
  .stSlider [data-baseweb="slider"] div[role="slider"] {{ background:{ACCENT} !important; }}
  [data-testid="stMetricValue"] {{ font-family:{MONO}; font-weight:600; color:{INK}; }}
  [data-testid="stMetricLabel"] {{ color:{MUTED}; font-weight:600; }}
  [data-baseweb="select"] > div {{ background:{PANEL} !important; border-color:{BORDER} !important;
                                   border-radius:8px !important; }}

  /* chips & captions */
  .stChip {{ display:inline-block; background:{PANEL_2}; border:1px solid {BORDER};
            border-radius:999px; padding:.18rem .65rem; font-size:.7rem; color:{MUTED};
            margin:.1rem .25rem .1rem 0; font-weight:500; }}
  .stChip.hot {{ color:{ACCENT}; border-color:{ACCENT}; background:{ACCENT_SOFT}; }}
  [data-testid="stCaptionContainer"] {{ color:{MUTED}; font-size:.74rem; }}
</style>
"""


def kpi(label: str, value: str, sub: str = "", tone: str = "") -> str:
    """Render one KPI tile as HTML (tone ∈ {'', 'pos', 'neg', 'accent'})."""
    klass = f" k-{tone}" if tone else ""
    vclass = f" {tone}" if tone else ""
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return (
        f'<div class="kpi{klass}"><div class="label">{label}</div>'
        f'<div class="value{vclass}">{value}</div>{sub_html}</div>'
    )


def signed(value: float, fmt: str = ",.0f") -> str:
    """Format a number with an explicit sign and a P&L colour class span."""
    cls = "pos" if value >= 0 else "neg"
    return f'<span class="{cls}">{value:+{fmt}}</span>'
