from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "SPDT_Technical_Documentation.pdf"

ACCENT = colors.HexColor("#9f1d20")
INK = colors.HexColor("#171a21")
MUTED = colors.HexColor("#616a78")
LIGHT = colors.HexColor("#f4f5f7")
GRID = colors.HexColor("#d9dde5")


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName="Times-Roman",
            fontSize=28,
            leading=34,
            textColor=INK,
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=15,
            leading=20,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=28,
        ),
        "cover_small": ParagraphStyle(
            "cover_small",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=11,
            leading=16,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="Times-Bold",
            fontSize=17,
            leading=22,
            textColor=INK,
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Times-Bold",
            fontSize=13,
            leading=17,
            textColor=INK,
            spaceBefore=10,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=10.2,
            leading=14.2,
            textColor=INK,
            spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=10.0,
            leading=14,
            leftIndent=14,
            firstLineIndent=-8,
            bulletIndent=4,
            textColor=INK,
            spaceAfter=3,
        ),
        "caption": ParagraphStyle(
            "caption",
            parent=base["Normal"],
            fontName="Times-Italic",
            fontSize=9,
            leading=12,
            textColor=MUTED,
            spaceBefore=3,
            spaceAfter=6,
        ),
        "table": ParagraphStyle(
            "table",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=8.6,
            leading=11,
            textColor=INK,
        ),
        "table_head": ParagraphStyle(
            "table_head",
            parent=base["Normal"],
            fontName="Times-Bold",
            fontSize=8.5,
            leading=10.5,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "code": ParagraphStyle(
            "code",
            parent=base["Code"],
            fontName="Courier",
            fontSize=8,
            leading=10,
            textColor=INK,
        ),
        "callout": ParagraphStyle(
            "callout",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=9.6,
            leading=13.5,
            textColor=INK,
            leftIndent=8,
            rightIndent=8,
            spaceBefore=4,
            spaceAfter=4,
        ),
    }


S = styles()


def P(text: str, style: str = "body"):
    return Paragraph(text, S[style])


def B(text: str):
    return P(text, "bullet")


def code(text: str):
    return Preformatted(text.strip("\n"), S["code"])


def table(rows, widths, header=True):
    data = []
    for r_i, row in enumerate(rows):
        style = S["table_head"] if header and r_i == 0 else S["table"]
        data.append([Paragraph(str(cell), style) for cell in row])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT if header else colors.white),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white if header else INK),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
            ]
        )
    )
    return t


def callout(text: str):
    t = Table([[P(text, "callout")]], colWidths=[16.1 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, ACCENT),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff7f7")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def footer(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(0.5)
    canvas.line(2.2 * cm, h - 1.35 * cm, w - 2.2 * cm, h - 1.35 * cm)
    canvas.setFont("Times-Roman", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(2.2 * cm, h - 1.05 * cm, "Structured Products Digital Twin - Technical Documentation")
    canvas.drawRightString(w - 2.2 * cm, 1.05 * cm, str(doc.page))
    canvas.restoreState()


def cover():
    story = [Spacer(1, 3.5 * cm)]
    story.append(P("Structured Products Digital Twin", "title"))
    story.append(P("Equity structuring desk, semi-static hedging, outcome lab and CCR/XVA seam", "subtitle"))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_rule())
    story.append(Spacer(1, 0.7 * cm))
    story.append(P("<b>Comprehensive Technical Documentation</b>", "subtitle"))
    story.append(P("From client brief to booked risk, hedge implementation, outcome evidence and governance", "cover_small"))
    story.append(Spacer(1, 1.0 * cm))
    story.append(
        table(
            [
                ["Scope", "NIFTY structured notes: autocallables, Phoenix, barrier reverse convertibles, capital-protected notes and worst-of baskets"],
                ["Method", "Snapshot-driven pricing under BS/LV/Heston/LSV, SSVI surface, Greeks, P&L explain, semi-static barrier replication"],
                ["Risk", "Book Greeks, stress, model reserve, dynamic hedge comparison, XVA/CCR charges and RAROC governance"],
                ["Stack", "Python quant engine + FastAPI + React/Vite dashboard; Docker deployment on Hugging Face Spaces"],
            ],
            [2.2 * cm, 13.4 * cm],
            header=False,
        )
    )
    story.append(Spacer(1, 4.2 * cm))
    story.append(P("Prepared as accompanying documentation for the SPDT project.", "cover_small"))
    story.append(P("Each major module is explained at three levels: concept, mathematics and code seam.", "cover_small"))
    story.append(Spacer(1, 1.2 * cm))
    story.append(_rule())
    story.append(PageBreak())
    return story


def _rule():
    t = Table([[""]], colWidths=[16.1 * cm], rowHeights=[2])
    t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 1.0, ACCENT)]))
    return t


def contents():
    rows = [
        ("1", "Introduction: the problem in plain language"),
        ("2", "System architecture and data flow"),
        ("3", "Notation and numeric anchors"),
        ("4", "Market snapshot and data boundary"),
        ("5", "Products as payoff graphs"),
        ("6", "Pricing models and Monte Carlo engine"),
        ("7", "Greeks, P&L attribution and model reserve"),
        ("8", "Structuring and price-to-par solve"),
        ("9", "Virtual book, dashboard and tabs"),
        ("10", "Semi-static hedging lifecycle"),
        ("11", "Outcome Lab"),
        ("12", "CCR/XVA seam and governance"),
        ("13", "Running, deployment and limitations"),
        ("14", "Tutorial: how to use the live tool"),
    ]
    story = [P("Contents", "h1")]
    story.append(
        table(
            [["No.", "Section"]] + rows,
            [1.1 * cm, 14.5 * cm],
        )
    )
    story.append(PageBreak())
    return story


def section_intro():
    return [
        P("1 Introduction: the problem in plain language", "h1"),
        P("1.1 What is being simulated", "h2"),
        P(
            "SPDT is a software simulation of an equity structured-products desk. It is not a single option calculator. "
            "It follows a note from client objective to proposed terms, fair value, booking, daily P&L explain, Greeks, "
            "stress, hedging, outcome evidence and counterparty-capital decision. The reference product is a NIFTY "
            "autocallable or Phoenix note: the investor receives an enhanced coupon in exchange for selling downside and "
            "barrier risk to the issuer.",
        ),
        P(
            "The core desk question is simple: if a client asks for income with conditional protection, what structure is "
            "fair, what risk does the desk inherit, how should that risk be hedged, and does the trade still make sense "
            "after counterparty credit and capital costs?",
        ),
        P("1.2 Why a desk twin is more useful than a pricer", "h2"),
        B("A pricer returns one PV. A desk twin explains how that PV changes, which note moved it, and what hedge or governance action follows."),
        B("A structured note is a portfolio of embedded options: coupons, autocall rights, knock-in puts, digitals, funding legs and sometimes correlation exposure."),
        B("The project therefore emphasizes workflow fidelity: snapshot in, report out; typed payoff components; book-level aggregation; and explicit model/data boundaries."),
        callout(
            "<b>Two rules govern the project.</b> First, faithful not fake: simplified components are named, not hidden. "
            "Second, the math is the asset: every screen should be defensible from first principles, not merely visually convincing."
        ),
        P("1.3 What this document covers", "h2"),
        P(
            "This document mirrors the project itself. It starts with the plain-language product intuition, then walks through "
            "architecture, notation, data, payoff construction, pricing, Greeks, structuring, semi-static hedging, Outcome Lab, "
            "the CCR/XVA seam, and finally a practical tutorial for using the dashboard."
        ),
        P("1.4 The running example", "h2"),
        P(
            "The running example is a two-year NIFTY Phoenix/autocallable. The client wants enhanced annual income and is "
            "willing to accept conditional protection: coupons are paid while NIFTY stays above a coupon barrier, the note "
            "autocalls if the index is above the autocall level on an observation date, and terminal capital is at risk only "
            "if a knock-in barrier has been observed. This single payoff is rich enough to exercise almost every desk function: "
            "path-dependent pricing, Greeks, barrier lifecycle state, semi-static replication, issuance outcomes and XVA exposure."
        ),
        P("1.5 What a reviewer should notice", "h2"),
        B("The project is not framed as live production infrastructure. It is framed as a production-shaped educational desk twin."),
        B("Every major output carries a boundary: synthetic versus real data, indicative hedge versus executable quote, model result versus observed performance."),
        B("The newest tabs - How to use, Semi-Static Hedging and Outcome Lab - were added to make the project easier for a desk reviewer to understand quickly."),
    ]


def architecture():
    rows = [
        ["Layer", "Package / screen", "Responsibility"],
        ["L1", "spdt/data", "Ingest, clean and freeze market data into MarketSnapshot objects."],
        ["L2", "spdt/vol", "SVI/SSVI implied-vol surface, arbitrage checks/repair and local-vol hooks."],
        ["L3", "spdt/products", "Product DSL: notes represented as composable payoff primitives and product classes."],
        ["L4", "spdt/pricing", "Analytic, PDE and Monte Carlo pricing under BS, LV, Heston and LSV-style variants."],
        ["L5", "spdt/greeks", "Bump, pathwise, likelihood-ratio and AAD-style sensitivities."],
        ["L6", "spdt/structurer", "Client brief to recommendation; solve coupon/barrier/participation to par."],
        ["L7-L12", "book, hedging, pnl, modelrisk, stress", "Book aggregation, hedge simulation, Taylor explain, reserve and scenarios."],
        ["L14", "webapp", "FastAPI plus React desk: Overview, Originate, Book & Risk, XVA, Validate, Semi-Static, Outcome Lab."],
        ["Seam", "integration/", "Only bridge between SPDT and the companion INR CCR/XVA engine."],
    ]
    return [
        P("2 System architecture and data flow", "h1"),
        P(
            "The system is layered. Low-level market and model code does not know about the dashboard; the dashboard consumes "
            "typed payloads from the FastAPI server. A single immutable market snapshot moves upward through the stack. This "
            "keeps historical replay, P&L attribution and model validation reproducible."
        ),
        table(rows, [1.4 * cm, 4.1 * cm, 10.2 * cm]),
        P("The one path that matters", "h2"),
        code(
            """
Market data -> RawMarketData -> MarketSnapshot
MarketSnapshot -> Product payoff -> Pricing engine
Pricing result -> Greeks -> Book aggregation -> P&L explain / stress / reserve
Booked trade -> Semi-static hedge and Outcome Lab
Exposure package -> CCR/XVA engine -> all-in coupon and governance
            """
        ),
        P(
            "The architectural constraint is deliberate: each layer consumes the output of the layer below and exposes a "
            "stable, typed surface upward. The only cross-world importer is integration/, where SPDT exposure packages are "
            "handed to the companion XVA/CCR engine."
        ),
        P("2.1 Why the seam matters", "h2"),
        P(
            "A common mistake in student projects is to merge every concern into one model object. SPDT avoids that. The equity "
            "structuring world and the CCR/XVA world have different responsibilities. The structuring engine knows the payoff, "
            "market snapshot and pricing model; the XVA engine knows exposure, default, funding, capital and governance. Their "
            "contract is the exposure package, not shared product internals."
        ),
        P("2.2 Dashboard data flow", "h2"),
        code(
            """
GET /api/desk
  -> build_desk_data()
  -> positions, greeks, pnl explain, stress, surface, catalog

POST /api/structure
  -> recommend()
  -> solve_to_par()
  -> staged trade payload

POST /api/semistatic
  -> live book trades
  -> constrained option-strip hedge

GET /api/outcomes
  -> source booked trade
  -> issuance study + hedge comparison + case study
            """
        ),
    ]


def notation():
    rows = [
        ["Symbol", "Meaning"],
        ["S", "Underlying spot level, e.g. NIFTY index level."],
        ["K", "Strike or contractual trigger level, depending on product leg."],
        ["B", "Barrier level, usually expressed as a percentage of initial fixing."],
        ["T", "Maturity in years; observation times define autocall/coupon dates."],
        ["r", "Discount rate used by the equity pricer; in hosted mode synthetic INR OIS-style."],
        ["q", "Dividend yield or carry on the equity underlying."],
        ["sigma", "Lognormal volatility; ATM or surface-implied depending on context."],
        ["PV", "Present value per 100 face unless stated otherwise."],
        ["Delta, Gamma, Vega", "First and second order sensitivities used in P&L explain and hedging."],
        ["EE / PFE / EAD", "Expected exposure, potential future exposure and exposure at default in CCR."],
        ["XVA", "Total charge convention: CVA + FVA + KVA + MVA - DVA."],
    ]
    anchors = [
        ["Quantity", "Current demo anchor", "Interpretation"],
        ["Book", "15 notes", "Small but complete portfolio for inspection."],
        ["Underlying", "NIFTY", "Hosted/demo universe is NIFTY-focused."],
        ["Outcome backtest", "Synthetic issuance cohorts", "Regime replay, not observed issued-note history."],
        ["Semi-static hedge", "Listed-style vanilla strip", "Indicative barrier-component replication, not exact full-note replication."],
        ["Data boundary", "Synthetic equity/rates on HF", "Local Bloomberg workbook only supplies MIFOR funding overlay."],
    ]
    return [
        P("3 Notation and numeric anchors", "h1"),
        P("3.1 Symbol table", "h2"),
        table(rows, [3.0 * cm, 12.5 * cm]),
        P("3.2 Regression and interpretation anchors", "h2"),
        table(anchors, [3.6 * cm, 4.3 * cm, 7.7 * cm]),
        callout(
            "A key naming caution: the Bloomberg workbook supplied locally contains MIFOR and USD/INR-related rates. "
            "SPDT treats it only as a funding overlay. It is not used as a NIFTY volatility source and is not represented "
            "as a true MIBOR/OIS discount curve unless such data is explicitly supplied."
        ),
    ]


def data_boundary():
    return [
        P("4 Market snapshot and data boundary", "h1"),
        P("4.1 Concept", "h2"),
        P(
            "Every model run starts from a MarketSnapshot: spot, valuation date, rates, dividend/carry assumptions, "
            "volatility surface and provenance. The snapshot abstraction is the reason the same engine can run in three modes: "
            "deterministic synthetic, public EOD/live data where available, or local Bloomberg overlay."
        ),
        P("4.2 Sources and what they mean", "h2"),
        table(
            [
                ["Source", "Used for", "Boundary"],
                ["Synthetic", "Default hosted demo and tests", "Generated spot/smile/rates; reproducible, not live market data."],
                ["NSE bhavcopy / Dhan", "Public or broker equity market data path", "Useful for spot/option-chain style inputs when configured."],
                ["FBIL / model OIS", "Rates bootstrap path", "India rates input where available; hosted fallback is synthetic INR OIS-style."],
                ["Bloomberg workbook", "Local MIFOR funding overlay", "Funding spread overlay only; FX vol/rates are labelled if unused."],
            ],
            [3.2 * cm, 4.4 * cm, 8.0 * cm],
        ),
        P("4.3 Snapshot-in, report-out", "h2"),
        code(
            """
raw = fetch(source)
snapshot = build_snapshot(raw, as_of)
surface = fit_ssvi(snapshot.options)
book = mark_book(snapshot, surface)
report = aggregate(book, pnl, greeks, stress, xva)
            """
        ),
        P(
            "No upper layer should scrape raw files or reinterpret market conventions. This is why the dashboard can state "
            "which data is synthetic, which is Bloomberg-derived, and which is a model assumption."
        ),
        P("4.4 Bloomberg workbook handling", "h2"),
        P(
            "The local Bloomberg file is useful, but it is not magically a complete equity-structuring market data pack. The "
            "project currently uses it where it is defensible: to infer a MIFOR-style funding spread overlay. It does not use "
            "FX vol as NIFTY vol, and it does not treat MIFOR as the same thing as a MIBOR/OIS discount curve. That honesty is "
            "important because mislabelled data is worse than synthetic data in a technical interview."
        ),
        P("4.5 Hosted versus local behavior", "h2"),
        table(
            [
                ["Mode", "What the user sees", "Why"],
                ["Hugging Face Space", "Synthetic masthead labels and model funding assumption.", "The Space cannot read private Bloomberg files from the laptop."],
                ["Local with workbook", "MIFOR-funding source label and Bloomberg funding overlay.", "The Excel path is supplied through environment variables."],
                ["Local without workbook", "Synthetic or public-data fallback depending on env.", "Keeps the app reproducible and always runnable."],
            ],
            [3.3 * cm, 5.8 * cm, 6.5 * cm],
        ),
    ]


def products_pricing():
    return [
        P("5 Products as payoff graphs", "h1"),
        P(
            "Structured notes are built from primitives: funding legs, coupons, autocall conditions, knock-in/downside legs, "
            "digitals, vanilla option exposures and correlation features. Representing a note as a typed payoff graph makes "
            "decomposition, risk attribution and hedge selection possible."
        ),
        table(
            [
                ["Product", "Economic intuition", "Main embedded risk"],
                ["Autocallable / Phoenix", "Enhanced coupon plus early redemption if NIFTY is above trigger.", "Short downside and short volatility near barriers."],
                ["Barrier reverse convertible", "Coupon funded by selling a down-and-in put.", "Jump in exposure after knock-in."],
                ["Capital-protected note", "Bond floor plus upside participation.", "Rates/funding plus call option exposure."],
                ["Worst-of basket", "Coupon funded by selling the weakest name in a basket.", "Correlation and worst-name crash risk."],
            ],
            [3.3 * cm, 6.4 * cm, 5.9 * cm],
        ),
        PageBreak(),
        P("6 Pricing models and Monte Carlo engine", "h1"),
        P("6.1 Black-Scholes baseline", "h2"),
        P(
            "The baseline equity model assumes lognormal dynamics dS/S = (r - q)dt + sigma dW. It is not sufficient for all "
            "barrier and smile effects, but it is the right control model because it gives closed-form intuition and fast "
            "regression anchors."
        ),
        code(
            """
model = BlackScholes(spot=S, r=r, q=q, sigma=atm_vol)
pv = price_mc(product, model, n_paths, seed)
delta, gamma, vega = bump_greeks(product, model)
            """
        ),
        P("6.2 Smile-aware extensions", "h2"),
        P(
            "The project includes SVI/SSVI surface construction, local-vol hooks, Heston-style stochastic volatility and an "
            "LSV-vs-LV reserve concept. The dashboard does not hide model limitations: validation and data-boundary labels "
            "are part of the product."
        ),
        P("6.3 Path-dependent payoff evaluation", "h2"),
        P(
            "Autocallables and Phoenix notes are evaluated path by path. Observation dates matter: a path can redeem early, "
            "continue with memory coupons, or knock in and expose the investor to terminal downside. This is also what makes "
            "their counterparty exposure profile distinct: expected exposure can collapse at autocall dates as redeemed paths leave the book."
        ),
        P("6.4 Product payoff pseudo-code", "h2"),
        code(
            """
for path in simulated_paths:
    alive = True
    memory_coupon = 0
    knocked_in = False
    for obs_date in schedule:
        if S[path, obs_date] <= knock_in:
            knocked_in = True
        if S[path, obs_date] >= coupon_barrier:
            pay_coupon(regular_coupon + memory_coupon)
            memory_coupon = 0
        else:
            memory_coupon += regular_coupon
        if S[path, obs_date] >= autocall_level:
            pay_principal()
            alive = False
            break
    if alive:
        pay_terminal_principal_or_downside(knocked_in)
            """
        ),
        P("6.5 What makes barriers difficult", "h2"),
        P(
            "Barrier products are sensitive to path discretisation, local volatility near the barrier, skew, and jump/gap risk. "
            "A clean implementation must distinguish contractual barrier state from today's mark. If the barrier has not been "
            "observed, current spot alone is not proof of historical knock-in. The Semi-Static Hedging tab makes that state explicit."
        ),
    ]


def greeks_structuring():
    return [
        P("7 Greeks, P&L attribution and model reserve", "h1"),
        P(
            "The desk P&L explain is a Taylor decomposition. For a one-day move, the book-level approximation is"
            " Delta dS + 0.5 Gamma dS^2 + Vega d sigma + cross terms, with the residual compared to full revaluation."
        ),
        table(
            [
                ["Component", "Role in the dashboard"],
                ["Delta", "Cash P&L for a spot move; drives day-to-day hedge direction."],
                ["Gamma", "Convexity; becomes important near barriers and autocall triggers."],
                ["Vega", "Vol-surface level risk; autocallable books are often short vol."],
                ["Vanna / Volga", "Smile and convex-vol effects; useful for explaining residuals."],
                ["Model reserve", "Difference between richer model and simpler benchmark, e.g. LSV - LV."],
            ],
            [3.3 * cm, 12.3 * cm],
        ),
        PageBreak(),
        P("8 Structuring and price-to-par solve", "h1"),
        P(
            "The Originate tab turns a client brief into a ranked product recommendation. A client can state target coupon, "
            "protection buffer, maturity, observation frequency and fee. The engine ranks structures by fit, then solves the "
            "free parameter so the model PV equals the issue target."
        ),
        code(
            """
brief = ClientBrief(target_coupon, max_downside, maturity, observations)
proposal = recommend(brief)
solved = solve_to_par(proposal, target_pv=100 - fee)
            """
        ),
        callout(
            "The client may ask for 12 percent income, but the model may solve a lower fair coupon. The dashboard separates "
            "client target, booked coupon, current fair coupon and post-XVA offerable coupon so the shortfall is explicit."
        ),
        P("8.1 The economics of a coupon solve", "h2"),
        P(
            "For an income note, the coupon is not an arbitrary marketing number. It is funded by the option premium the investor "
            "gives to the issuer, typically through downside or barrier exposure. If the requested coupon is too high for the "
            "chosen protection level, the desk must either lower the coupon, move the barrier closer, extend maturity, use a basket, "
            "or accept worse economics after fees and XVA."
        ),
        P("8.2 Why the tool shows alternatives", "h2"),
        P(
            "A real structurer does not show only one answer. They compare structures: an autocallable may maximize income, a capital-protected "
            "note may fit conservative clients, and a worst-of basket may fund a higher coupon by selling correlation and weakest-name risk. "
            "The alternatives panel is included to make that trade-off visible."
        ),
    ]


def dashboard_tabs():
    rows = [
        ["Tab", "Purpose", "First thing to check"],
        ["How to use", "Reviewer guide for what the tool is and how each tab should be read.", "Recommended review path."],
        ["Overview", "Book NAV, P&L explain, top movers and stress.", "P&L residual and largest movers."],
        ["Originate", "Client brief to recommended structure and solve-to-par result.", "Coupon/protection sliders and product alternatives."],
        ["Book & Risk", "Trade-level details, Greeks and stresses for the 15-note book.", "Click a NOTE-* row."],
        ["Counterparty & XVA", "Exposure, XVA, capital and governance over the same notes.", "RAROC and approval decision."],
        ["Validate", "Model checks, surface health and explain diagnostics.", "Any flags before trusting results."],
        ["Semi-Static Hedging", "Barrier risk replication and residual hedge ladder.", "Selected barrier trade and strip notional."],
        ["Outcome Lab", "Synthetic issuance study, hedge comparison and case study.", "Backtest disclosure and hedge table."],
    ]
    return [
        P("9 Virtual book, dashboard and tabs", "h1"),
        P(
            "The dashboard is designed like a reviewer-facing desk. It starts with a how-to guide, then lets the user move "
            "from executive book view to origination, risk, XVA, model validation, hedging implementation and outcome evidence."
        ),
        table(rows, [3.2 * cm, 8.2 * cm, 4.2 * cm]),
    ]


def semistatic_outcomes():
    return [
        P("10 Semi-static hedging lifecycle", "h1"),
        P("10.1 Concept", "h2"),
        P(
            "A barrier note contains path-dependent downside optionality that cannot be perfectly hedged by a small set of "
            "listed vanilla options. The semi-static tab therefore does something narrower and defensible: it projects the "
            "barrier component onto a constrained listed-style strip, then reports the tracking error and residual Greeks."
        ),
        P("10.2 Lifecycle logic", "h2"),
        B("Trade IDs come from the live 15-note book, not a hardcoded table."),
        B("Barriers are tied to contractual initial fixing, not recalculated from today's spot."),
        B("Knock-in/knock-out state is explicit; the app does not infer a historical event from current spot alone."),
        B("Gross strip inventory is constrained, so the hedge is implementable-style rather than an unconstrained fit."),
        P("10.3 What the residual ladder means", "h2"),
        P(
            "The residual risk chart groups target and hedge Greeks by barrier bucket. Delta is displayed as cash P&L for a "
            "+1 percent spot move; gamma as the convex P&L contribution for a 1 percent squared move. The dynamic hedger owns "
            "the difference left after the static strip."
        ),
        PageBreak(),
        P("11 Outcome Lab", "h1"),
        P(
            "The Outcome Lab was added to answer a common desk-review question: not just 'what is the model price?', but "
            "'what are the outcomes, hedge trade-offs and decision consequences?' It is explicitly labelled synthetic where applicable."
        ),
        table(
            [
                ["Study", "What it answers", "Important caveat"],
                ["Issuance cohort backtest", "How the same NIFTY autocallable behaves across simulated issue dates/regimes.", "Synthetic regime replay, not real issued-note performance."],
                ["Hedge comparison", "Unhedged vs delta-only vs semi-static vs hybrid: P&L sigma, ES95, turnover and cost.", "Uses model paths and policy constraints."],
                ["Client-to-desk case", "Client target, booked/fair/post-XVA coupon, hedge selection, EAD, capital and RAROC.", "Illustrative desk decision tied to the source trade."],
            ],
            [4.2 * cm, 7.3 * cm, 4.1 * cm],
        ),
        P("11.1 What is being backtested", "h2"),
        P(
            "The backtest is an issuance-cohort study: it asks how the same payoff would behave if issued repeatedly across "
            "many simulated monthly start dates and market regimes. It is not a database of real client notes and it is not "
            "claimed as observed NIFTY note performance. The correct phrase is synthetic issuance-cohort backtest."
        ),
        P("11.2 Reading the hedge comparison", "h2"),
        P(
            "Risk cut is the percentage reduction in the chosen tail or dispersion measure versus the unhedged note. A high risk "
            "cut with extreme turnover or cost may still be unattractive. This is why the table shows P&L sigma, ES95, turnover, "
            "cost and policy pass/fail together rather than picking the lowest-risk line blindly."
        ),
    ]


def xva_running():
    return [
        P("12 CCR/XVA seam and governance", "h1"),
        P(
            "SPDT integrates with a separate INR CCR/XVA engine built as its own project. The two systems meet at one seam: "
            "an ExposurePackage containing a path-by-time NPV cube, curves and counterparty assumptions. SPDT remains the "
            "equity structuring desk; the companion engine owns CVA/FVA/KVA/MVA, capital and governance."
        ),
        code(
            """
SPDT product model -> mark-to-future NPV cube
ExposurePackage -> netting / CSA / WWR overlays
Charge = CVA + FVA + KVA + MVA - DVA
All-in solve: PV = par - fee - XVA
Governance: EAD/PFE limits + RAROC hurdle -> decision
            """
        ),
        P(
            "This is intentionally architected as two desks over one seam, not one giant product model. That mirrors the way "
            "front-office structuring and CCR/XVA functions interact: exposure is the contract between them."
        ),
        PageBreak(),
        P("13 Running, deployment and limitations", "h1"),
        P("13.1 Local run", "h2"),
        code(
            """
uvicorn webapp.server:app --host 127.0.0.1 --port 8077

# optional local Bloomberg MIFOR funding overlay
SPDT_SOURCE=bloomberg-rates \\
SPDT_BLOOMBERG_RATES_XLSX=\"/path/to/Data for Intern's usage.xlsx\" \\
uvicorn webapp.server:app --host 127.0.0.1 --port 8077
            """
        ),
        P("13.2 Hugging Face deployment", "h2"),
        P(
            "The Dockerfile builds the React frontend and serves it with FastAPI from one Uvicorn process on port 7860. "
            "Hosted mode cannot read the local Bloomberg file, so the app honestly labels hosted equity/rates inputs as synthetic or model assumptions."
        ),
        P("13.3 Limitations", "h2"),
        B("No claim of bank production infrastructure, live exchange connectivity, or internal dealer marks."),
        B("Synthetic regime studies are educational unless replaced with point-in-time historical closes and issued-note records."),
        B("Semi-static hedges are indicative barrier-component hedges, not guaranteed executable quotes."),
        B("The XVA seam is faithful and extensive, but full regulatory CVA capital and rates/swap production scope live outside SPDT."),
        P("13.4 Quality gates used while building", "h2"),
        B("Python unit tests cover pricing, Greeks, products, replication, outcomes, server routes and XVA integration seams."),
        B("The React frontend is type-checked and production-built before deploy."),
        B("The dashboard labels the source and boundary of the data instead of hiding synthetic assumptions."),
        B("The repo documentation includes architecture, layer walkthroughs, project talk track and ADRs for key design decisions."),
    ]


def tutorial():
    return [
        P("14 Tutorial: how to use the live tool", "h1"),
        P("14.1 First pass for a reviewer", "h2"),
        B("Open How to use. Read the recommended path and the data-boundary note."),
        B("Go to Overview. Confirm book NAV, top movers, P&L explain and worst stress."),
        B("Open Originate. Move target coupon/protection and observe the solved structure and alternatives."),
        B("Go to Book & Risk. Click any NOTE-* trade and inspect terms, Greeks and stress."),
        B("Open Counterparty & XVA. Change CDS/funding/hurdle and watch the decision move."),
        B("Open Semi-Static Hedging. Select a barrier trade and review strip, notional limit and residual ladder."),
        B("Open Outcome Lab. Read the backtest disclosure, hedge comparison and client-to-desk case."),
        P("14.2 Interview talk track", "h2"),
        P(
            "A concise explanation is: 'I built a digital twin of an equity structured-products desk. It structures NIFTY notes, "
            "marks a live 15-note book, explains P&L and risk, tests semi-static barrier hedges, shows synthetic outcome evidence, "
            "and integrates with a separate INR CCR/XVA engine through an exposure-cube seam so the same trade can be evaluated "
            "for CVA, FVA, capital and governance.'"
        ),
        callout(
            "The strongest way to present the project is not to oversell it as a bank system. Present it as a production-shaped, "
            "honestly bounded student build that demonstrates desk workflow, quant ownership and awareness of model/data limits."
        ),
        P("14.3 Suggested five-minute demo order", "h2"),
        table(
            [
                ["Minute", "Action", "Message"],
                ["0-1", "How to use + Overview", "This is a desk twin, not a one-off pricer."],
                ["1-2", "Originate", "Client terms become a solved structure and alternatives."],
                ["2-3", "Book & Risk + Validate", "The note joins a book, produces Greeks, stress and validation signals."],
                ["3-4", "Semi-Static Hedging", "Barrier risk is partly transferred into a constrained listed-style strip."],
                ["4-5", "Outcome Lab + XVA", "Model outputs are tied to outcomes, hedge costs, capital and governance."],
            ],
            [2.0 * cm, 4.6 * cm, 9.0 * cm],
        ),
    ]


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=2.2 * cm,
        rightMargin=2.2 * cm,
        topMargin=1.7 * cm,
        bottomMargin=1.6 * cm,
        title="SPDT Technical Documentation",
        author="Shreyas Mashelkar",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=footer)])
    story = []
    story.extend(cover())
    story.extend(contents())
    for i, part in enumerate([
        section_intro,
        architecture,
        notation,
        data_boundary,
        products_pricing,
        greeks_structuring,
        dashboard_tabs,
        semistatic_outcomes,
        xva_running,
        tutorial,
    ]):
        story.extend(part())
        if i != 9:
            story.append(PageBreak())
    doc.build(story)
    print(OUT)


if __name__ == "__main__":
    build()
