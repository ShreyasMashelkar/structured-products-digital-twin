"""SEC EDGAR 424B2 pricing supplements — real term sheets with the issuer's own valuation.

This is the only external price benchmark in the project. Every other check in the validation
pack is internal: it asks whether the model agrees with itself, with its inputs, or with a
second estimator of the same quantity. None of them can detect a model that is wholly coherent
and priced 4% away from where the market actually transacts.

US structured notes are registered securities. Every one is filed with the SEC as a 424B2
pricing supplement containing the complete economic terms **and**, since the 2012 FINRA
guidance on retail structured products, the issuer's disclosed *initial estimated value* — the
bank's own model value of the note, published alongside the price it sold at.

**How to read that benchmark.** The estimated value is deliberately below the offering price:
it is net of the dealer's margin and the issuer's funding benefit. A $10 note with a $9.58
estimated value carries roughly 4.2% of fee and funding load. So a model that reproduces the
$10 offering price has *not* validated; a model that reproduces the $9.58 has matched the
issuer's own risk-neutral value. The informative statistic is the distribution of
``model_value − disclosed_estimated_value`` across many notes:

* a tight band centred near zero means the model agrees with the street;
* a tight band centred elsewhere means a constant bias — usually a funding or dividend
  assumption, and correctable;
* a band that *widens or drifts* with tenor, with vol level, or between single-name and
  worst-of is the genuine finding, because it localises where the model breaks down.

**Preliminary versus final.** Preliminary supplements are also filed as 424B2 and look almost
identical, but carry blank dates and an estimated value expressed as a *range* ("expected to be
between $9.20 and $9.50"). Those cannot be benchmarked against — there is no single number and
no fixed terms. :func:`parse_filing` records which kind it parsed and
:func:`is_benchmarkable` is the gate; silently averaging a range would fabricate a data point.

SEC access requires a declaring User-Agent with contact details and asks for under 10 requests
per second. Both are honoured; set ``SPDT_SEC_USER_AGENT`` to your own contact string.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

try:  # certifi's CA bundle — robust across machines (esp. macOS python.org builds)
    import certifi

    _SSL_CONTEXT: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - falls back to the system trust store
    _SSL_CONTEXT = None

from spdt.products.catalog import Autocallable
from spdt.products.termsheet import TermSheet

_SEARCH = "https://efts.sec.gov/LATEST/search-index"
_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"
_CACHE_DIR = Path("data/edgar_cache")
_DEFAULT_UA = "spdt-research (structured-products research; contact: set SPDT_SEC_USER_AGENT)"
_MIN_INTERVAL = 0.15  # seconds between SEC requests — under their 10/s ceiling

_last_request = 0.0

# Observation frequency as stated in the term sheet, in payments per year.
_FREQUENCIES: dict[str, int] = {
    "monthly": 12, "quarterly": 4, "semi-annual": 2, "semiannual": 2, "annual": 1,
}


def _user_agent() -> str:
    return os.environ.get("SPDT_SEC_USER_AGENT", _DEFAULT_UA)


def _get(url: str, *, timeout: float = 40.0) -> bytes:
    """Fetch ``url`` from SEC, rate-limited to stay inside their published ceiling."""
    global _last_request
    wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    request = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
    with urllib.request.urlopen(  # noqa: S310 (fixed SEC hosts)
        request, timeout=timeout, context=_SSL_CONTEXT
    ) as response:
        payload = response.read()
    _last_request = time.monotonic()
    return payload


# --- search ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class FilingRef:
    """A search hit: enough to locate and fetch one filing."""

    accession: str
    document: str
    cik: str
    issuer: str
    filed: date

    @property
    def url(self) -> str:
        return f"{_ARCHIVE}/{self.cik.lstrip('0')}/{self.accession.replace('-', '')}/{self.document}"


def search_filings(
    phrase: str = "Autocallable Contingent Coupon",
    *,
    start: date | None = None,
    end: date | None = None,
    forms: str = "424B2",
    limit: int = 40,
) -> list[FilingRef]:
    """Full-text search EDGAR for pricing supplements matching ``phrase``.

    EDGAR's full-text index only covers 2001 onward and accepts a single quoted phrase —
    combining two quoted phrases returns HTTP 500 — so the filter is deliberately coarse here
    and the precise screening happens in :func:`parse_filing`.
    """
    quoted_phrase = '"' + phrase + '"'  # EDGAR needs the phrase quoted to match it as a unit
    params = [f"q={quote(quoted_phrase)}", f"forms={forms}"]
    if start:
        params.append(f"startdt={start.isoformat()}")
    if end:
        params.append(f"enddt={end.isoformat()}")

    # EDGAR serves 10 hits per page and allows paging to 9,990. The shelf files thousands of
    # supplements a year and only a minority are *final* (priced) rather than preliminary, so a
    # benchmark run has to page deep to accumulate a usable sample — an earlier 100-hit cap here
    # made the shelf look far thinner than it is.
    refs: list[FilingRef] = []
    for offset in range(0, min(limit, 9_990), 10):
        url = f"{_SEARCH}?{'&'.join(params)}&from={offset}"
        try:
            payload = json.loads(_get(url))
        except Exception:  # noqa: BLE001 - a failed page should not lose the earlier ones
            break
        hits = payload.get("hits", {}).get("hits", [])
        if not hits:
            break
        for hit in hits:
            accession, _, document = hit["_id"].partition(":")
            source = hit.get("_source", {})
            names = source.get("display_names") or ["unknown"]
            filed = source.get("file_date")
            refs.append(
                FilingRef(
                    accession=accession,
                    document=document,
                    cik=(source.get("ciks") or ["0"])[0],
                    issuer=names[0],
                    filed=date.fromisoformat(filed) if filed else date.today(),
                )
            )
        if len(refs) >= limit:
            break
    return refs[:limit]


def fetch_filing_text(ref: FilingRef, *, cache: bool = True) -> str:
    """Download a filing and reduce it to normalised plain text."""
    path = _CACHE_DIR / f"{ref.accession}.txt"
    if cache and path.exists():
        return path.read_text()

    html = _get(ref.url).decode("utf-8", "ignore")
    text = _to_text(html)
    if cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return text


def _to_text(html: str) -> str:
    """Strip markup and normalise entities and whitespace to a single searchable line."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    replacements = {
        "&nbsp;": " ", "&amp;": "&", "&#8220;": '"', "&#8221;": '"',
        "&ldquo;": '"', "&rdquo;": '"', "&#8217;": "'", "&rsquo;": "'",
        "&sect;": " ", "&#167;": " ", "&#8212;": "-", "&mdash;": "-",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Hex entities (&#x201c;) must be handled as well as decimal ones — the Goldman shelf emits
    # hex exclusively, and leaving them in splits words that the term regexes then miss.
    text = re.sub(r"&#x[0-9a-fA-F]+;", " ", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# --- parsing --------------------------------------------------------------------------------


@dataclass(frozen=True)
class NoteFiling:
    """One parsed pricing supplement — terms plus the issuer's disclosed valuation."""

    issuer: str
    url: str
    filed: date
    is_final: bool  # False for a preliminary supplement (blank dates, EV given as a range)

    denomination: float = 10.0
    offering_price: float = 100.0  # as a percentage of denomination
    estimated_value: float | None = None  # per denomination unit, in currency
    coupon_per_period: float | None = None  # as a fraction of denomination
    coupon_barrier: float | None = None  # fraction of the starting value
    knock_in: float | None = None
    call_level: float | None = None
    periods_per_year: int | None = None
    memory: bool = False
    non_call_months: float = 0.0
    # Downside buffer fraction (0.10 for "with a 10% Buffer"). A buffered note loses only the
    # decline beyond the buffer, so ignoring it undervalues the note by the buffer's put-spread
    # — which showed up in the benchmark as buffered notes "unreachable, model too LOW".
    buffer: float = 0.0
    pricing_date: date | None = None
    maturity_date: date | None = None
    underlyings: tuple[str, ...] = ()
    cusip: str = ""
    # Worst-of notes pay on the *least*-performing underlying, so they are short dispersion and
    # their value depends on correlation — the one pricing input with no clean market
    # observable. They are ~two thirds of current US issuance, so this is the common case.
    is_worst_of: bool = False
    # ``(ticker, starting_value)`` — each name's closing price on the pricing date, i.e. the
    # per-name strike a worst-of is struck at.
    starting_values: tuple[tuple[str, float], ...] = ()

    @property
    def tenor_years(self) -> float | None:
        if self.pricing_date is None or self.maturity_date is None:
            return None
        return (self.maturity_date - self.pricing_date).days / 365.0

    @property
    def estimated_value_pct(self) -> float | None:
        """Disclosed estimated value as a percentage of par — directly comparable to a model PV."""
        if self.estimated_value is None or self.denomination <= 0:
            return None
        return 100.0 * self.estimated_value / self.denomination

    @property
    def disclosed_load_pct(self) -> float | None:
        """Offering price minus estimated value: the fee and funding load, in points of par.

        This is the number a model must *not* try to reproduce. It is the dealer's margin, and a
        model that matches the offering price rather than the estimated value has simply
        absorbed someone else's fee into its risk-neutral valuation.
        """
        ev = self.estimated_value_pct
        return None if ev is None else self.offering_price - ev

    @property
    def is_benchmarkable(self) -> bool:
        """Whether this filing carries enough fixed detail to price and compare against.

        Preliminary supplements are excluded on principle rather than by best effort: their
        estimated value is a range and their dates are blank, so any single number derived from
        one is invented.
        """
        return (
            self.is_final
            and self.estimated_value is not None
            and self.coupon_per_period is not None
            and self.coupon_barrier is not None
            and self.knock_in is not None
            and self.call_level is not None
            and self.periods_per_year is not None
            and self.tenor_years is not None
            and self.tenor_years > 0.0
        )

    def observation_times(self) -> tuple[float, ...]:
        """Observation schedule in year fractions, honouring the non-call period."""
        if self.periods_per_year is None or self.tenor_years is None:
            return ()
        step = 1.0 / self.periods_per_year
        n = max(1, round(self.tenor_years * self.periods_per_year))
        return tuple(round(step * i, 6) for i in range(1, n + 1))

    def to_term_sheet(self) -> TermSheet:
        """The project's own record type, so a filed note flows through the ordinary pipeline."""
        return TermSheet(
            product_type="Autocallable",
            underlyings=self.underlyings,
            notional=100.0,
            observation_times=self.observation_times(),
            params={
                "coupon_rate": (self.coupon_per_period or 0.0) / self.denomination,
                "coupon_barrier": self.coupon_barrier,
                "knock_in": self.knock_in,
                "autocall_level": self.call_level,
                "memory": self.memory,
                "non_call_months": self.non_call_months,
                "issuer": self.issuer,
                "cusip": self.cusip,
                "estimated_value_pct": self.estimated_value_pct,
                "source_url": self.url,
            },
        )

    def to_autocallable(self, *, initial_fixing: float | None = None) -> Autocallable:
        """A priceable product with the filed terms, on a notional of 100 (i.e. percent of par).

        Observations inside the non-call period keep paying coupons but cannot redeem the note.
        The catalog's :class:`Autocallable` has a single autocall level for every date, so a
        non-call period is expressed by pushing that level out of reach on the early dates —
        which is what the term sheet means economically.
        """
        return Autocallable(
            notional=100.0,
            observation_times=self.observation_times(),
            coupon_rate=(self.coupon_per_period or 0.0) / self.denomination,
            autocall_level=self.call_level or 1.0,
            coupon_barrier=self.coupon_barrier or 0.8,
            knock_in=self.knock_in or 0.6,
            memory=self.memory,
            initial_fixing=initial_fixing,
            buffer=self.buffer,
        )


_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_DATE = re.compile(rf"({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})")


def _parse_dates(text: str) -> list[date]:
    out: list[date] = []
    for m in _DATE.finditer(text):
        try:
            out.append(datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date())
        except ValueError:
            continue
    return out


def _pct_after(text: str, label: str) -> float | None:
    """Fraction from a term line stating a level as a percentage of the starting value.

    The shelves phrase the same fact three ways and all three appear in current filings::

        Threshold Value: 80.00 (80% of the Starting Value)        # BofA / Merrill
        Coupon Barrier: 80.00, which is 80% of the Starting Value  # Goldman
        Coupon Barrier: 80%                                        # bare

    Matching only the first — which an earlier version did — silently returned ``None`` for
    every Goldman filing, i.e. quietly discarded a whole issuer's shelf rather than failing.
    """
    patterns = (
        rf"{label}\s*:?\s*[\d,.]*\s*\(\s*([\d.]+)\s*%",           # ... 80.00 (80% ...)
        rf"{label}\s*:?\s*[\d,.]*\s*,?\s*which is\s*([\d.]+)\s*%",  # ... 80.00, which is 80%
        rf"{label}\s*:?\s*([\d.]+)\s*%",                          # ... 80%
    )
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return float(m.group(1)) / 100.0
    return None


def worst_of_levels(text: str, label: str) -> dict[str, tuple[float, float]]:
    """Per-underlying levels for a worst-of note: ``{ticker: (level, fraction_of_start)}``.

    Worst-of supplements state each barrier once per underlying, as an absolute price and a
    percentage of that name's own starting value::

        Coupon Barrier: META: $347.31 (60.00% of its Starting Value).
                        AAPL: $181.35 (60.00% of its Starting Value).
                        TSLA: $196.51 (60.00% of its Starting Value).

    The single-underlying pattern cannot match this — the ticker sits between the label and the
    number — which is why every worst-of filing previously parsed with empty barriers. Since
    worst-of is roughly two thirds of the current US shelf, that silently excluded most of the
    market from the benchmark.

    Returning the absolute levels as well as the percentages is what makes the starting values
    recoverable (``level ÷ fraction``), and those are the strikes the note is struck at.
    """
    per_name = re.compile(
        r"([A-Z.]{1,6})\s*:\s*\$\s?([\d,.]+)\s*\(\s*([\d.]+)\s*%\s*of its Starting Value", re.I
    )
    # The label appears several times — in the narrative summary as well as in the definitive
    # terms section — and only the latter is followed by the per-name levels. Scanning a window
    # after each occurrence and taking the first that actually yields names is more robust than
    # trying to express "the terms table" as one regex.
    # The terms section lists the labels back to back:
    #   Coupon Barrier: META: $347.31 (60%)... Threshold Value: META: ... Call Value: META: ...
    # so a window has to be anchored *and* truncated. Anchored, because an early narrative
    # mention of the label is not followed by levels and would otherwise capture the next
    # table's; truncated, because an unbounded window reads on into the following label and
    # returns its percentages instead. Getting this wrong is silent — it yields a well-formed
    # 100% "coupon barrier" that is really the call level.
    boundary = re.compile(
        r"(?:Threshold Value|Call Value|Coupon Barrier|Starting Value|"
        r"Contingent Coupon Payment|Observation Date)\s*:",
        re.I,
    )
    matches: list[tuple[str, str, str]] = []
    for m in re.finditer(rf"{label}\s*:", text, re.I):
        window = text[m.end(): m.end() + 800]
        if not re.match(r"\s*[A-Z.]{1,6}\s*:\s*\$", window):
            continue  # this occurrence is narrative prose, not the terms table
        stop = boundary.search(window, 1)
        matches = per_name.findall(window[: stop.start()] if stop else window)
        if matches:
            break
    if not matches:
        return {}
    out: dict[str, tuple[float, float]] = {}
    for ticker, level, pct in matches:
        try:
            out[ticker] = (float(level.replace(",", "")), float(pct) / 100.0)
        except ValueError:
            continue
    return out


def _common_fraction(levels: dict[str, tuple[float, float]]) -> float | None:
    """The barrier fraction shared by every underlying, or ``None`` if they differ.

    Worst-of notes in practice set the same percentage on every name, but that is a market
    convention rather than a rule. Returning ``None`` on disagreement forces the caller to
    handle a genuinely per-name barrier rather than silently pricing all names off the first
    one's level.
    """
    if not levels:
        return None
    fractions = {round(f, 6) for _, f in levels.values()}
    return next(iter(fractions)) if len(fractions) == 1 else None


def _closing_prices(text: str) -> dict[str, float]:
    """Each underlying's closing price on the pricing date, as the filing reports it.

    These are the note's actual strikes. Recovering them matters because a worst-of is struck
    per name: pricing it off a common notional level would misplace every barrier relative to
    where each stock actually was.
    """
    out: dict[str, float] = {}
    for ticker, price in re.findall(
        r"Closing Market Price of ([A-Z.]{1,6}) was \$\s?([\d,.]+)", text
    ):
        try:
            out[ticker] = float(price.replace(",", ""))
        except ValueError:
            continue
    return out


def _prose_pct(text: str, lead: str) -> float | None:
    """Fraction from summary prose like ``... is greater than or equal to 60% of the Starting Value``."""
    m = re.search(rf"{lead}\s*([\d.]+)\s*%\s*of the Starting Value", text, re.I)
    return float(m.group(1)) / 100.0 if m else None


def parse_filing(text: str, *, issuer: str = "", url: str = "", filed: date | None = None) -> NoteFiling:
    """Extract terms and the disclosed estimated value from a pricing supplement's text.

    Written against the phrasing the major shelves actually use (BofA/Merrill, Goldman, Citi,
    JPMorgan). Any field that cannot be found stays ``None`` rather than defaulting to a
    plausible value — a wrong barrier silently defaulted to 80% would corrupt the benchmark
    while looking perfectly healthy, which is the failure mode this whole module exists to
    detect elsewhere.
    """
    filed = filed or date.today()

    # Estimated value. A final filing states one number; a preliminary states a range.
    is_range = bool(
        re.search(r"estimated value[^.]{0,120}?expected to be between", text, re.I)
    )
    ev_match = re.search(
        r"(?:initial\s+)?estimated value of (?:the|your) notes[^.$]{0,150}?\$\s?([\d,]+\.\d+)",
        text, re.I,
    )
    estimated_value = float(ev_match.group(1).replace(",", "")) if ev_match else None

    denom_match = re.search(r"\$\s?([\d,]+(?:\.\d+)?)\s+principal amount per (?:unit|note)", text, re.I)
    denomination = float(denom_match.group(1).replace(",", "")) if denom_match else 10.0

    # Per-period coupon, quoted in currency per unit.
    coupon = None
    cm = re.search(
        r"Contingent Coupon Payment[^.]{0,120}?(?:is|of)\s*\$\s?([\d.]+)\s*per (?:unit|note)",
        text, re.I,
    )
    if cm:
        coupon = float(cm.group(1))
    else:  # some shelves quote a rate per annum instead of a cash amount
        rm = re.search(r"Contingent Coupon Rate[^.]{0,80}?([\d.]+)\s*%\s*per annum", text, re.I)
        if rm:
            annual = float(rm.group(1)) / 100.0
            freq_guess = next(
                (v for k, v in _FREQUENCIES.items() if re.search(rf"{k}\s+(?:Coupon )?Observation", text, re.I)),
                None,
            )
            if freq_guess:
                coupon = denomination * annual / freq_guess

    periods = next(
        (v for k, v in _FREQUENCIES.items()
         if re.search(rf"{k}\s+(?:Coupon\s+)?(?:Observation|Payment)", text, re.I)),
        None,
    )

    non_call = 0.0
    ncm = re.search(r"beginning approximately\s+(\d+)\s+(month|year)", text, re.I)
    if ncm:
        non_call = float(ncm.group(1)) * (12.0 if ncm.group(2).lower() == "year" else 1.0)

    # Pricing / settlement / maturity appear as a run of three dates under their headers.
    pricing_date = maturity_date = None
    header = re.search(r"Pricing Date\s*\*?\s*Settlement Date\s*\*?\s*Maturity Date\s*\*?(.{0,160})", text, re.I)
    if header:
        dates = _parse_dates(header.group(1))
        if len(dates) >= 3:
            pricing_date, maturity_date = dates[0], dates[2]
    if maturity_date is None:
        dm = re.search(rf"due\s+({_MONTHS})\s+\d{{1,2}},\s+\d{{4}}", text, re.I)
        if dm:
            found = _parse_dates(dm.group(0))
            maturity_date = found[0] if found else None

    cusip_match = re.search(r"CUSIP\s*(?:No\.?)?\s*:?\s*([0-9A-Z]{9})", text, re.I)

    buffer_match = re.search(r"with a\s*([\d.]+)\s*%\s*Buffer", text, re.I) or re.search(
        r"Buffer\s*(?:Amount|Percentage)?\s*:\s*([\d.]+)\s*%", text, re.I
    )
    buffer = float(buffer_match.group(1)) / 100.0 if buffer_match else 0.0

    # Levels: prefer the definitive terms table, fall back to the summary prose. Single-stock
    # Goldman notes in particular state "...is greater than or equal to 60% of the Starting
    # Value" in the summary and never repeat it as a labelled table row, so a table-only parser
    # drops them despite the level being unambiguous.
    is_worst_of = bool(re.search(r"Worst[- ]Performing|Least[- ]Performing", text, re.I))
    wo_coupon = worst_of_levels(text, r"Coupon Barrier")
    wo_threshold = worst_of_levels(text, r"Threshold Value")
    wo_call = worst_of_levels(text, r"Call Value")
    closing = _closing_prices(text)

    coupon_barrier = (
        _common_fraction(wo_coupon)
        or _pct_after(text, r"(?:Applicable\s+)?Coupon Barrier")
        or _prose_pct(text, r"Coupon Observation Date is greater than or equal to")
    )
    knock_in = (
        _common_fraction(wo_threshold)
        or _pct_after(text, r"Threshold Value")
        or _prose_pct(text, r"Ending Value is (?:less than|greater than or equal to)")
    )
    if knock_in is None:
        # Stated as a permitted *fall* rather than a level: "if the value of the Market Measure
        # has decreased by more than 40%" is a 60% knock-in. Converting rather than skipping
        # matters because this is the house style for single-stock notes, which are exactly the
        # high-vol cases a benchmark most needs.
        drop = re.search(r"has decreased by more than\s*([\d.]+)\s*%", text, re.I)
        if drop:
            knock_in = 1.0 - float(drop.group(1)) / 100.0
    call_level = (
        _common_fraction(wo_call)
        or _pct_after(text, r"Call (?:Value|Level|Threshold)")
        or _prose_pct(
            text, r"Call Observation Date[^.]{0,80}?(?:is|at)\s+(?:greater than or equal to|or above)"
        )
    )
    if call_level is None and re.search(
        r"Call Observation Date[^.]{0,120}?at or above the Starting Value", text, re.I
    ):
        call_level = 1.0  # "at or above the Starting Value" is 100% stated without the number

    # Underlying names come from the level lines themselves, which is more reliable than the
    # quoted-shorthand scan: a ticker that carries a barrier is definitionally an underlying.
    wo_any = wo_call or wo_coupon or wo_threshold
    names = list(wo_any)
    starts: dict[str, float] = {k: v for k, v in closing.items() if k in names}
    for ticker, (level, fraction) in wo_any.items():
        if ticker not in starts and fraction > 0:
            starts[ticker] = level / fraction  # recover the strike the level was quoted off

    return NoteFiling(
        issuer=issuer,
        url=url,
        filed=filed,
        is_final=not is_range and estimated_value is not None and pricing_date is not None,
        denomination=denomination,
        estimated_value=estimated_value,
        coupon_per_period=coupon,
        coupon_barrier=coupon_barrier,
        knock_in=knock_in,
        call_level=call_level,
        periods_per_year=periods,
        memory=bool(re.search(r"with Memory", text, re.I)),
        non_call_months=non_call,
        buffer=buffer,
        pricing_date=pricing_date,
        maturity_date=maturity_date,
        underlyings=tuple(names) if names else _underlyings(text),
        cusip=cusip_match.group(1) if cusip_match else "",
        is_worst_of=is_worst_of,
        starting_values=tuple(starts.items()),
    )


# Abbreviations that appear in the same quoted-shorthand form as a ticker but are not the
# note's underlying: the issuing bank and its distributor, the exchanges the underlying trades
# on, the regulators named in the boilerplate, and the index publishers. Without this the
# "underlyings" of a Bank of America note reliably came back as ('BAC', 'NYSE', 'FINRA').
_NOT_UNDERLYINGS = frozenset({
    "SEC", "USD", "LLC", "MTN", "ETF", "FINRA", "NYSE", "NASDAQ", "CBOE", "IRS", "CFTC",
    "BAC", "GS", "GSG", "JPM", "JPMS", "CIBC", "MS", "C", "WFC", "RBC", "TD", "UBS", "HSBC",
    "MLPF", "BOFAS", "SPDJI", "LBMA", "ICE", "FCA", "ISDA", "OCC", "DTC", "SIPC",
})


def _underlyings(text: str) -> tuple[str, ...]:
    """Ticker symbols the note references, as quoted in the filing's own shorthand.

    Best-effort: the reliable identification of the underlying is the CUSIP plus the prose
    description, and a caller doing a real benchmark run should confirm against those rather
    than trust this list. It is here to make a parsed filing legible at a glance, not to drive
    pricing.
    """
    tickers = re.findall(r'"([A-Z]{1,5})"\s*\)', text)
    seen: list[str] = []
    for t in tickers:
        if t not in seen and t not in _NOT_UNDERLYINGS:
            seen.append(t)
    return tuple(seen[:5])


def load_filings(
    phrase: str = "Autocallable Contingent Coupon",
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 40,
    benchmarkable_only: bool = True,
    cache: bool = True,
) -> list[NoteFiling]:
    """Search, fetch and parse filings; by default keep only those that can be benchmarked."""
    filings: list[NoteFiling] = []
    for ref in search_filings(phrase, start=start, end=end, limit=limit):
        try:
            text = fetch_filing_text(ref, cache=cache)
        except Exception:  # noqa: BLE001 - one unavailable document must not sink the batch
            continue
        filing = parse_filing(text, issuer=ref.issuer, url=ref.url, filed=ref.filed)
        if benchmarkable_only and not filing.is_benchmarkable:
            continue
        filings.append(filing)
    return filings
