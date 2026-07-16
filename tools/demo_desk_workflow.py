"""Phase 10 demo: the full structured-products desk workflow, end to end, in one run.

Structure a note for a client brief → price it with Greeks → charge XVA and gate it →
render the term sheet → recommend a delta hedge → paper-execute it → attribute the P&L.
Every step reuses the same engine functions the dashboard serves — this is a narrative
over the real system, not a parallel implementation.

Run offline (synthetic desk):        python3 tools/demo_desk_workflow.py
Run on live data (network, no keys): SPDT_LIVE=1 SPDT_SOURCE=bhavcopy python3 tools/demo_desk_workflow.py
"""

from __future__ import annotations

from datetime import datetime, timezone


def main(*, verbose: bool = True, n_paths: int = 12_000) -> dict:
    import webapp.server as server
    from spdt.products.termsheet import TermSheet
    from spdt.reporting.termsheet_render import PricingSummary, render_term_sheet

    def say(msg: str) -> None:
        if verbose:
            print(msg)

    # 1 — market: whatever snapshot the desk is marked on (synthetic offline, live with env flags)
    d = server._desk()
    say(f"1. MARKET      {d['underlying']} spot {d['spot']:,.0f} · ATM vol "
        f"{d['model']['atm_vol'] * 100:.1f}% · r {d['model']['r'] * 100:.2f}% · "
        f"source {d['data_source']} ({d['data_date']})")

    # 2 — structure: client wants income; solve the coupon to par
    proposal = server.structure(server.StructureRequest(
        target_coupon=0.12, max_downside=0.30, maturity=1.5, obs_per_year=4, objective="income",
    ))
    say(f"2. STRUCTURE   {proposal.label} · solved {proposal.solved_display} "
        f"(achievable: {proposal.achievable})")

    # 3 — price the solved note with Greeks and scenarios
    price_request = server.PriceRequest(
        product_type=proposal.product_type, notional=100.0,
        observation_times=proposal.book_observation_times,
        maturity=proposal.book_maturity, params=proposal.book_params,
    )
    priced = server.price(price_request)
    say(f"3. PRICE       PV {priced['pv']:.2f} ± {priced['std_error']:.2f} · "
        f"Δcash {priced['greeks']['cash_delta']:.2f}/1% · vega {priced['greeks']['vega_pt']:.2f}/pt")

    # 4 — counterparty charge + governance gate
    xva_result = server.xva(server.XvaRequest(
        product_type=proposal.product_type, notional=100.0,
        observation_times=proposal.book_observation_times,
        maturity=proposal.book_maturity, params=proposal.book_params,
        cds_spread_bps=180.0, funding_spread_bp=50.0, hurdle_rate=0.10,
        cost_of_capital=0.12, collateralised=True, n_paths=n_paths // 2,
    ))
    say(f"4. XVA         total charge {xva_result['charge']['total']:.3f} "
        f"(CVA {xva_result['charge']['cva']:.3f} / FVA {xva_result['charge']['fva']:.3f}) · "
        f"decision {xva_result['decision']}")

    # 5 — client-facing term sheet from the same terms the pricer used
    sheet = render_term_sheet(
        TermSheet(product_type=proposal.product_type, underlyings=(d["underlying"],),
                  notional=100.0, observation_times=tuple(proposal.book_observation_times),
                  params=proposal.book_params),
        PricingSummary(pv=priced["pv"], std_error=priced["std_error"]),
    )
    say(f"5. TERM SHEET  rendered ({len(sheet)} chars of markdown)")

    # 6 — hedge the *position's* delta with front-month futures. A client buys real size,
    # not one note: 10,000 units of the 100-notional note ≈ a ₹1cr ticket.
    client_units = 10_000
    spot = float(d["spot"])
    position_delta = float(priced["greeks"]["delta"]) * client_units
    say(f"   BOOK        client buys {client_units:,} units → position Δ {position_delta:,.0f}")
    recommendation = server.hedge_recommend(server.HedgeRequest(
        book_delta=position_delta,
        future=server.InstrumentIn(
            instrument_id=1, segment=2, symbol=f"{d['underlying']}-FUT",
            bid=spot - 1.0, ask=spot + 1.0, ltp=spot,
            quote_timestamp=datetime.now(timezone.utc), lot_size=1,
        ),
    ))
    orders = ", ".join(f"{o['side']} {o['qty']:.0f} {o['symbol']}" for o in recommendation["orders"])
    say(f"6. HEDGE       {recommendation['approval_state']} · {orders or 'no orders needed'} · "
        f"est cost {recommendation['estimated_cost']:.2f}")

    # 7 — paper-execute the recommendation against the same quote it was sized on
    if recommendation["orders"] and recommendation["approval_state"] == "PROPOSED":
        executed = server.execute_recommendation(server.ExecuteRequest(
            recommendation_id=recommendation["recommendation_id"],
        ))
        say(f"7. EXECUTE     {' / '.join(o['status'] for o in executed['orders'])} (paper)")
    else:
        say("7. EXECUTE     skipped — nothing to do")

    # 8 — explain the hedge P&L: realized / unrealized / fees / spread
    attribution = server.execution_attribution_report(server.AttributionRequest(
        marks={"2:1": spot},
    ))
    t = attribution["totals"]
    say(f"8. ATTRIBUTION realized {t['realized_pnl']:.2f} · fees {t['fees']:.2f} · "
        f"spread {t['spread_cost']:.2f} · net {t['net_pnl'] if t['net_pnl'] is None else round(t['net_pnl'], 2)}")

    say("\nDone: brief → structure → price → XVA → term sheet → hedge → paper fill → P&L explain.")
    return {
        "structure": proposal.label,
        "pv": priced["pv"],
        "xva_total": xva_result["charge"]["total"],
        "decision": xva_result["decision"],
        "term_sheet": sheet,
        "recommendation": recommendation,
        "attribution": attribution,
    }


if __name__ == "__main__":
    main()
