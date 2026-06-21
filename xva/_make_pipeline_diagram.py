"""Generate a Bloomberg-terminal-style pipeline architecture diagram for the
INR Multi-Asset XVA Engine. Auto-sized boxes, top-down layout (no overlaps)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# ── Bloomberg palette ───────────────────────────────────────────────
BG, PANEL = "#0a0a0a", "#0d1117"
AMBER, BLUE, GREEN, RED, PURPLE = "#ff6600", "#00aaff", "#00cc66", "#ff3b30", "#b06cff"
TEXT, DIM, GRID = "#e8e8e8", "#8899aa", "#1a2230"
MONO = "monospace"

# ── geometry constants ──────────────────────────────────────────────
SPINE_X, SPINE_W = 24, 52
HEAD_PAD, ITEM_TOP, ITEM_DY, BOT_PAD = 2.6, 5.2, 2.55, 1.4
GAP = 3.2  # vertical gap between bands (for the arrow)

def box_height(n):       # auto height for n item-lines
    return HEAD_PAD + BOT_PAD + ITEM_TOP - HEAD_PAD + n * ITEM_DY + 0.4

STAGES = [
    (BLUE,  "1", "MARKET DATA", "src/data_ingestion",
     ["FIMMDA · RBI DBIE · CCIL · NSE   (all free)",
      "3-tier:  Live  →  Cache  →  Calibrated fallback"]),
    (BLUE,  "2", "CURVE CONSTRUCTION", "src/curves",
     ["OIS discount curve   (bootstrapped from par rates)",
      "Multi-curve projection · G-Sec · CDS credit curve"]),
    (AMBER, "3", "SIMULATE THE FUTURE", "src/montecarlo",
     ["Hull-White 1F  —  exact OU transition + bond pricing",
      "Antithetic variates · Quasi-MC (Sobol) · HW2F",
      "Calibration:  OLS on historical MIBOR"]),
    (AMBER, "4", "EXPOSURE CUBE", "src/exposure",
     ["Reprice trades on every  (path × time)",
      "Parquet-persisted  →  EE · EPE · EEPE · PFE · ENE"]),
    (GREEN, "5", "COLLATERAL & NETTING", "src/csa · src/portfolio",
     ["CSA:  threshold · MTA · IA · netting sets",
      "Margin Period of Risk close-out  (grid-independent)"]),
    (GREEN, "6", "XVA STACK", "src/xva",
     ["CVA · DVA · FVA · KVA · MVA (SIMM)",
      "Credit curves · CDS bootstrap · survival weighting",
      "Sensitivities:  CS01 · IR01 · AAD greeks"]),
    (RED,   "7", "REGULATORY CAPITAL", "src/sa_ccr · src/economic_capital",
     ["SA-CCR:   EAD = α · (RC + PFE)   →   RWA",
      "BA-CVA · FRTB SA-CVA (delta/vega/curvature)",
      "Economic Capital  —  ASRF / Vasicek @ 99.9%"]),
    (PURPLE,"8", "GOVERNANCE & DECISION", "src/workflow · limits · raroc",
     ["Incremental XVA (identical-path) → Limits (RAG)",
      "RAROC / EVA  →  TRADE APPROVAL  (approve / reject)",
      "PnL & XVA attribution · Stress · IMM backtest",
      "Wrong-Way Risk (Cox process) · IFRS-13 · Reporting"]),
]

# ── compute total height & canvas ───────────────────────────────────
heights = [box_height(len(s[4])) for s in STAGES]
TITLE_H = 5.6
TOP = 4.0                      # top margin
FOOTER_H = 12.0
total = TOP + TITLE_H + 2.5 + sum(heights) + GAP * (len(STAGES) - 1) + FOOTER_H + 2
W = 100

fig, ax = plt.subplots(figsize=(17, total * 0.182), dpi=150)
fig.patch.set_facecolor(BG); ax.set_facecolor(BG)
ax.set_xlim(0, W); ax.set_ylim(0, total); ax.axis("off")

# dotted grid
for gx in range(0, W + 1, 4):
    ax.plot([gx, gx], [0, total], color=GRID, lw=0.3, alpha=0.22, zorder=0)
for gy in range(0, int(total) + 1, 4):
    ax.plot([0, W], [gy, gy], color=GRID, lw=0.3, alpha=0.22, zorder=0)

def arrow(x0, y0, x1, y1, color, scale=22, lw=2.4, ls="-", alpha=1.0):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>",
                 mutation_scale=scale, color=color, lw=lw, zorder=2,
                 alpha=alpha, linestyle=ls))

def stage(y_bottom, h, accent, num, title, sub, items):
    x, w = SPINE_X, SPINE_W
    ax.add_patch(FancyBboxPatch((x, y_bottom), w, h,
                 boxstyle="round,pad=0.3,rounding_size=0.8", linewidth=1.7,
                 edgecolor=accent, facecolor=PANEL, zorder=3))
    top = y_bottom + h
    ax.add_patch(FancyBboxPatch((x + 1.0, top - 3.3), 4.6, 2.5,
                 boxstyle="round,pad=0.1,rounding_size=0.4", linewidth=0,
                 facecolor=accent, zorder=4))
    ax.text(x + 3.3, top - 2.05, num, ha="center", va="center", color="#0a0a0a",
            fontsize=13, fontweight="bold", family=MONO, zorder=5)
    ax.text(x + 7.2, top - 2.05, title, ha="left", va="center", color=accent,
            fontsize=15, fontweight="bold", family=MONO, zorder=5)
    ax.text(x + w - 1.4, top - 2.05, sub, ha="right", va="center", color=DIM,
            fontsize=8.6, style="italic", family=MONO, zorder=5)
    ty = top - ITEM_TOP
    for it in items:
        ax.text(x + 2.8, ty, "▸", ha="left", va="center", color=accent,
                fontsize=8.5, family=MONO, zorder=5)
        ax.text(x + 5.4, ty, it, ha="left", va="center", color=TEXT,
                fontsize=9.7, family=MONO, zorder=5)
        ty -= ITEM_DY
    return top, y_bottom  # (top, bottom)

def side(cx, cy, w, h, color, title, items):
    x, y = cx - w / 2, cy - h / 2
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                 boxstyle="round,pad=0.25,rounding_size=0.6", linewidth=1.2,
                 edgecolor=color, facecolor="#0b0e13", zorder=3, linestyle="--"))
    ax.text(cx, y + h - 1.9, title, ha="center", va="center", color=color,
            fontsize=10, fontweight="bold", family=MONO, zorder=5)
    ty = y + h - 4.4
    for it in items:
        ax.text(cx, ty, it, ha="center", va="center", color=DIM, fontsize=8.3,
                family=MONO, zorder=5)
        ty -= 2.2

# ── Title bar ───────────────────────────────────────────────────────
ty0 = total - TOP - TITLE_H
ax.add_patch(FancyBboxPatch((4, ty0), 92, TITLE_H,
             boxstyle="round,pad=0.3,rounding_size=0.8", linewidth=1.7,
             edgecolor=AMBER, facecolor=PANEL, zorder=3))
ax.text(7.0, ty0 + 3.4, "BBG", ha="left", va="center", color="#0a0a0a",
        fontsize=12, fontweight="bold", family=MONO,
        bbox=dict(boxstyle="round,pad=0.3", fc=AMBER, ec="none"), zorder=5)
ax.text(16, ty0 + 3.6, "INR MULTI-ASSET   CCR / XVA   ENGINE", ha="left",
        va="center", color=TEXT, fontsize=18.5, fontweight="bold", family=MONO)
ax.text(16, ty0 + 1.5, "END-TO-END PIPELINE ARCHITECTURE   ·   free-data, CPU-only",
        ha="left", va="center", color=DIM, fontsize=9.5, family=MONO)
ax.text(94, ty0 + 2.8, "● LIVE", ha="right", va="center", color=GREEN,
        fontsize=10, fontweight="bold", family=MONO)

# ── Draw bands top→bottom, record centers ───────────────────────────
y_cursor = ty0 - 2.5
centers = []
for (accent, num, title, sub, items), h in zip(STAGES, heights):
    yb = y_cursor - h
    top, bot = stage(yb, h, accent, num, title, sub, items)
    centers.append((accent, (top + bot) / 2, top, bot))
    if num != "8":
        arrow(50, bot - 0.1, bot - GAP + 0.3 + 0, 0, accent) if False else \
            arrow(50, bot - 0.1, 50, bot - GAP + 0.5, accent)
    y_cursor = bot - GAP

# ── Left rail inputs ────────────────────────────────────────────────
# data sources → stage 1
side(12.5, centers[0][1], 17, 9.4, BLUE, "FREE SOURCES",
     ["FIMMDA bonds", "RBI DBIE rates", "CCIL / NDS-OM", "NSE  Nifty"])
arrow(21, centers[0][1], SPINE_X - 0.3, centers[0][1], BLUE, scale=15, lw=1.5)

# exotics / multi-asset → exposure cube (stage 4)
side(12.5, centers[3][1], 17, 11.0, AMBER, "EXOTICS &\nMULTI-ASSET",
     ["Bermudan (LSM)", "Cross-ccy  3-factor", "Equity (GBM / BSM)", "Hybrid netting set"])
arrow(21, centers[3][1], SPINE_X - 0.3, centers[3][1], AMBER, scale=15, lw=1.5)

# reuse-cube feedback loop (cube → XVA without re-sim)
ax.add_patch(FancyArrowPatch((SPINE_X - 0.5, centers[3][1] - 1.5),
             (SPINE_X - 0.5, centers[5][1] + 1.5), arrowstyle="-|>",
             color=DIM, lw=1.3, ls=(0, (3, 2)), zorder=2,
             connectionstyle="arc3,rad=0.32"))
ax.text(18.4, (centers[3][1] + centers[5][1]) / 2, "reuse cube\n(no re-sim)",
        ha="center", va="center", color=DIM, fontsize=7.8, style="italic", family=MONO)

# ── Right rail: consuming desks ─────────────────────────────────────
ax.text(89, centers[0][2] + 1.5, "CONSUMING DESKS", ha="center", va="center",
        color=DIM, fontsize=9, fontweight="bold", family=MONO)
desks = [
    ("CCR DESK",     "EE/PFE · limits",     centers[3][1], BLUE),
    ("XVA DESK",     "CVA/FVA · CS01 hedge", centers[5][1], GREEN),
    ("CAPITAL MGMT", "SA-CCR · EconCap",     centers[6][1], RED),
    ("GOVERNANCE",   "RAROC · approve",      centers[7][1], PURPLE),
]
for name, dsc, cy, col in desks:
    side(89, cy, 18, 6.2, col, name, [dsc])
    arrow(SPINE_X + SPINE_W + 0.3, cy, 80, cy, col, scale=15, lw=1.5)

# ── Footer: the master equation + stats ─────────────────────────────
fy = centers[7][3] - GAP - 4.0
ax.text(50, fy + 1.8,
        "Clean MTM  −  CVA  +  DVA  −  FVA  −  KVA  −  MVA   =   RISKY ALL-IN PRICE",
        ha="center", va="center", color=AMBER, fontsize=12.5, fontweight="bold",
        family=MONO, bbox=dict(boxstyle="round,pad=0.6", fc=PANEL, ec=AMBER, lw=1.5))
# legend
legend = [("INPUT / SIM", BLUE), ("EXPOSURE", AMBER), ("CREDIT / XVA", GREEN),
          ("CAPITAL", RED), ("GOVERNANCE", PURPLE)]
lx = 24
for lab, col in legend:
    ax.add_patch(plt.Rectangle((lx, fy - 3.0), 1.3, 1.3, color=col, zorder=5))
    ax.text(lx + 1.9, fy - 2.35, lab, ha="left", va="center", color=DIM,
            fontsize=8, family=MONO)
    lx += 11.2
ax.text(50, fy - 5.6,
        "Hull-White Monte Carlo  ·  exact bond pricing  ·  231 tests  ·  34-page dashboard",
        ha="center", va="center", color=DIM, fontsize=9, family=MONO)

plt.subplots_adjust(left=0.01, right=0.99, top=0.995, bottom=0.005)
out = "XVA_Engine_Pipeline_Diagram.png"
plt.savefig(out, facecolor=BG, dpi=150, bbox_inches="tight", pad_inches=0.25)
print("saved", out, "canvas H =", round(total, 1))
