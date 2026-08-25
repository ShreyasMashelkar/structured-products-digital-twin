"""Model validation (L8) — evidence that the engine behaves, not just that it runs.

Everything below layer 7 answers "what is this note worth?". This layer answers the question
a model-risk reviewer actually asks: **"why should I believe that number?"** Those are
different questions and the second one is not automatically answered by the first.

The pack has four independent legs, deliberately chosen so that each can fail without the
others noticing — a validation suite whose tests all share one assumption validates nothing:

* :mod:`spdt.validation.asof` — rebuild the market as it stood on a historical date, so every
  other leg can be run in a *stressed* regime rather than only in today's calm one.
* :mod:`spdt.validation.greeks_crosscheck` — the same Greek computed three structurally
  different ways (adjoint, finite difference, closed form). Agreement is evidence; a single
  method agreeing with itself is not.
* :mod:`spdt.validation.sensitivity` — how far the solved coupon moves when the inputs it is
  least sure about move. A price that is precise but unstable is not a price.
* :mod:`spdt.validation.realized` — what the note *actually did* on the path that happened,
  against what it was priced to do. The only leg that touches reality rather than the model's
  own assumptions.

The report generator in :mod:`spdt.validation.report` runs all four across market regimes and
emits the artefact. Findings are reported whether or not they flatter the engine; a validation
pack that never fails anything is a marketing document.
"""

from spdt.validation.asof import AsOfMarket, REGIMES, build_asof_market
from spdt.validation.greeks_crosscheck import GreekComparison, cross_check_greeks
from spdt.validation.realized import RealizedComparison, compare_priced_vs_realized
from spdt.validation.sensitivity import SensitivityTable, coupon_sensitivity

__all__ = [
    "AsOfMarket",
    "GreekComparison",
    "REGIMES",
    "RealizedComparison",
    "SensitivityTable",
    "build_asof_market",
    "compare_priced_vs_realized",
    "coupon_sensitivity",
    "cross_check_greeks",
]
