"""The ``MarketSnapshot`` — the central immutable abstraction (ADR-0001, design doc §7).

Every layer above L1 consumes a snapshot and emits reports; nothing above the data layer
touches raw market data. A snapshot is **content-addressed**: its ``content_hash`` is a
deterministic digest of its economic contents, so re-running a given business date yields
byte-identical risk numbers ("official close") and historical replay is a simple iterator
over snapshots.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from enum import Enum
from functools import cached_property
from typing import Any

from spdt.core.provenance import Provenance
from spdt.core.types import CorrelationMatrix, Curve, DividendSchedule, Underlying

# Floats are rounded before hashing so that representationally-equal snapshots
# (e.g. 0.1 vs 0.1 reconstructed) hash identically. 12 dp is well inside our numerical
# tolerance (vanillas agree across methods to 1e-6) yet stable across platforms.
_HASH_FLOAT_DP = 12


def _canonicalize(obj: Any) -> Any:
    """Convert ``obj`` into a JSON-friendly, order-stable structure for hashing.

    Handles the value types that appear in a snapshot — dates, enums, dataclasses,
    mappings, sequences, floats — recursively. Any object exposing its own
    ``content_hash`` (e.g. a calibrated ``VolSurface`` from the vol layer, once built) is
    represented by that hash, which keeps ``core`` decoupled from layers it must not import.
    """
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        return round(obj, _HASH_FLOAT_DP)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    # A pre-hashed object (e.g. VolSurface) stands in for its full contents.
    content_hash = getattr(obj, "content_hash", None)
    if isinstance(content_hash, str):
        return {"__hash__": content_hash}
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _canonicalize(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Mapping):
        # Emit a list of [key, value] pairs sorted by canonical key, so that neither dict
        # ordering nor non-string keys (e.g. dates in a curve) affect the hash.
        pairs = [[_canonicalize(k), _canonicalize(obj[k])] for k in obj]
        pairs.sort(key=lambda kv: json.dumps(kv[0], sort_keys=True))
        return pairs
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(x) for x in obj]
    raise TypeError(f"cannot canonicalize {type(obj).__name__} for hashing")


@dataclass(frozen=True)
class MarketSnapshot:
    """An immutable, versioned view of "the market as of ``date``" (ADR-0001).

    The ``surfaces`` are typed structurally (``Mapping[str, Any]``) rather than against a
    concrete ``VolSurface`` so that ``core`` does not depend on ``spdt.vol``; a surface only
    needs to expose a ``content_hash`` to participate in the snapshot's own hash.
    """

    date: date
    spots: Mapping[Underlying, float]
    ois_curve: Curve
    funding_curve: Curve
    surfaces: Mapping[Underlying, Any]
    dividends: Mapping[Underlying, DividendSchedule]
    provenance: Provenance
    correlation: CorrelationMatrix | None = None

    @cached_property
    def content_hash(self) -> str:
        """SHA-256 over the snapshot's canonical economic contents.

        Provenance tags are *excluded*: they describe data lineage, not the numbers a price
        depends on, so flipping a tag from observed→interpolated must not change the hash of
        an otherwise-identical market.
        """
        canonical = {
            "date": self.date.isoformat(),
            "spots": _canonicalize(self.spots),
            "ois_curve": _canonicalize(self.ois_curve),
            "funding_curve": _canonicalize(self.funding_curve),
            "surfaces": _canonicalize(self.surfaces),
            "dividends": _canonicalize(self.dividends),
            "correlation": _canonicalize(self.correlation),
        }
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @property
    def short_hash(self) -> str:
        """First 16 hex chars of :attr:`content_hash` — for snapshot filenames (§7)."""
        return self.content_hash[:16]
