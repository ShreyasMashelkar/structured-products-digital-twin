# Draft reply to Siddharth Dave

Working notes for a LinkedIn follow-up. **Not for sending as-is** — edit into your own voice
before it goes anywhere, and check every number against the current
[`MODEL_VALIDATION_REPORT.md`](MODEL_VALIDATION_REPORT.md) first, since the figures below were
true when written and the report regenerates.

Two things to get right in the framing:

* He said *validate before expanding scope*. The strongest possible reply is that you did, and
  that the validation **found something that changed the project** — not that you added
  features. Lead with the negative finding; it is the most credible thing in the whole message.
* He said he is not a quant and that a quant should review the model. Do not oversell. Say what
  you measured, say what is still weak, and ask him the specific question you actually want
  answered.

---

## Option A — the full version

> Thanks again for the review — it changed what I worked on, so I wanted to close the loop.
>
> I took the "validate before expanding scope" point literally and stopped adding products. Two
> of your three areas turned out to be quick, and the third turned into the actual finding.
>
> **Rates.** The Hull-White 2-factor model was already written but wasn't wired into the
> exposure engine — only the 1-factor was. Switching it raised CVA on a 5y swap by about 90%,
> which looked like a big result until I variance-matched the two models first. Matched, the
> genuine curve-shape effect is +3.4%; the rest was just the second factor adding variance. I'd
> rather report the 3.4%.
>
> **Volatility and validation — this is where it went sideways.** I built a proper calibration
> report (fit RMSE per expiry and per moneyness bucket, not just the arbitrage check) and ran it
> on stressed dates: 2018 IL&FS, March 2020, the 2022 hiking cycle. The result was that the
> long-dated NIFTY surface was fitting a flat ~80% vol out to five years in March 2020, which
> can't be right — a crisis term structure is steeply inverted.
>
> The cause is that NSE publishes a settlement price for every listed contract whether or not it
> traded. On 2020-03-23 the 2023 and 2024 expiries had literally zero contracts traded and zero
> open interest, and those marks were feeding the surface. Screening on volume and open interest
> turns the flat 80% into 135% at three days falling to 48% at nine months — the shape you'd
> expect.
>
> The consequence is the uncomfortable part: once you only keep contracts that actually traded,
> no historical date supports a reliable quote past about a year. So the 3-year autocallable I'd
> been pricing was being priced off an extrapolated surface the whole time. That's a data limit
> rather than a model bug, but it does mean the flagship product wasn't supported by the data.
>
> So I added US data, and the difference is stark — SPX fits at 24bps RMSE with usable quotes out
> to 5.3 years, against 70–630bps and under a year on NIFTY, and CBOE gives two-sided markets so
> transaction costs are measured instead of assumed.
>
> That also let me do the thing I couldn't do before, which is check the model against something
> external. US structured notes are filed with the SEC with full terms *and* the issuer's own
> disclosed estimated value. The catch is that the difference between my price and theirs has two
> free parameters — vol and funding — so one number can't identify either. Inverting for vol
> instead, since that has a listed market to check against, a Goldman single-stock note implies
> 48.7% where the listed 1-year ATM is 48.1%.
>
> Following that through, about two thirds of current US issuance is worst-of on single stocks,
> where per-leg vols are observable and correlation isn't — so correlation becomes the one free
> parameter and you can back it out of notes that actually priced. Across the notes I could
> solve, the disclosed values imply correlations of 0.74–0.95, and for most of them they sit at
> or above what my model reaches even at correlation ≈ 1. Directionally that matches dealers
> marking correlation high when they sell worst-of, but I'd treat it as an upper bound rather
> than a measurement: I'm using flat ATM vol with no skew, and my vols are current while the
> notes were priced weeks or months ago. Both push the number up.
>
> Still weak, and I'd rather say so: no skew in the pricing (the knock-in sits in the put wing,
> which is exactly where flat ATM is worst), a constant rate on the equity side, and the sample
> is small.
>
> Code is here if it's useful: github.com/ShreyasMashelkar/structured-products-digital-twin —
> it's public, I just never sent you the link, which is probably why you couldn't get to it.
>
> The question I'd genuinely like a view on: does the implied-correlation number look like a
> sensible way to sanity-check a worst-of book, or is there a standard approach I'm missing? And
> if you know someone on a structuring or model-validation desk who'd spare 20 minutes to poke
> holes in it, I'd take that gladly.

---

## Option B — the short version

Use if the thread has gone quiet or you'd rather not send a wall of text.

> Thanks again — the review changed what I worked on, so quick update.
>
> I stopped adding products and validated instead. The finding was uncomfortable: NSE publishes
> settlement prices for contracts that never traded, and those were feeding my vol surface. On
> 2020-03-23 the 2023 and 2024 expiries had zero contracts traded and zero open interest, and the
> surface was reading a flat 80% vol out to five years. Screening on volume gives 135% falling to
> 48% — the inverted shape a crisis should have.
>
> The consequence: once you keep only traded contracts, no historical NIFTY date supports a
> reliable quote past ~1 year, so the 3-year autocallable was being priced off an extrapolation.
> I've added US data where the same calibration fits at 24bps out to 5.3 years, and started
> benchmarking against the issuers' own disclosed values in SEC filings — one note implies 48.7%
> vol against a listed 48.1%.
>
> On your rates point: the HW2F swap raised CVA ~90%, but variance-matched the real curve-shape
> effect is only +3.4%. Reporting the 3.4%.
>
> Repo: github.com/ShreyasMashelkar/structured-products-digital-twin (public — I never sent the
> link, which is probably why you couldn't access it).
>
> If you know anyone on a structuring or model-validation desk willing to poke holes in it, I'd
> appreciate the introduction.

---

## Before sending

- [ ] Re-run `python3 -m spdt.validation.report` and confirm every figure quoted above.
- [ ] Confirm the repo link resolves in a logged-out browser.
- [ ] Cut anything that reads as boasting. The findings carry themselves; adjectives dilute them.
- [ ] Keep the ask concrete and small. "20 minutes to poke holes" is answerable; "any advice"
      is not.
