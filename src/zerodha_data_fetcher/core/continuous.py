"""Pure continuous-series stitching for consecutive futures contracts.

Given the per-contract OHLC frames produced by the fetch path, build a single
front-month continuous series:

1. **Window by expiry (roll rule = calendar expiry).** Each contract owns the
   bars in ``(previous_expiry, its_expiry]``; overlapping bars from an
   already-rolled contract are dropped.  This uses only the ``Expiry`` dates
   already available — no volume/OI crossover (which would need data the
   ``oms`` endpoint may not return reliably for expired contracts).
2. **Optionally back-adjust the price gap at each roll seam.** The newest
   contract is the anchor and is never adjusted; older segments are shifted
   (``diff``) or scaled (``ratio``) so the series is continuous at each seam.
   ``none`` fabricates nothing and leaves absolute prices intact.

This module is deliberately free of any network/manager wiring so it can be
unit-tested on synthetic frames.  Choosing a back-adjust method other than
``none`` re-anchors history whenever the newest contract changes, so pin the
set of contracts (an as-of view) if you need reproducible output.
"""

from datetime import date
from typing import List, Optional, Sequence, Tuple

import pandas as pd

ADJUST_METHODS = ("none", "ratio", "diff")
_PRICE_COLUMNS = ("Open", "High", "Low", "Close")


def _window_segments(
    segments: Sequence[Tuple[date, pd.DataFrame]],
    date_column: str,
) -> List[pd.DataFrame]:
    """Slice each contract to the bars it 'owns' by expiry order."""
    ordered = sorted(segments, key=lambda item: item[0])
    prev_expiry: Optional[date] = None
    windowed: List[pd.DataFrame] = []
    for expiry, frame in ordered:
        parsed = pd.to_datetime(frame[date_column], errors="coerce").dt.date
        mask = parsed <= expiry
        if prev_expiry is not None:
            mask &= parsed > prev_expiry
        segment = frame[mask]
        if not segment.empty:
            windowed.append(segment.reset_index(drop=True))
        prev_expiry = expiry
    return windowed


def stitch_segments(
    segments: Sequence[Tuple[date, pd.DataFrame]],
    *,
    adjust: str = "none",
    date_column: str = "Date",
    price_column: str = "Close",
) -> pd.DataFrame:
    """Stitch per-contract frames into one continuous front-month series.

    Args:
        segments: ``(expiry_date, ohlc_frame)`` pairs, one per contract.
            Order is normalized ascending by expiry internally.
        adjust: ``"none"`` (raw, no fabrication), ``"ratio"`` (multiplicative
            back-adjust), or ``"diff"`` (additive back-adjust).  The newest
            contract is the unadjusted anchor.
        date_column: Column holding each bar's date.
        price_column: Column used to measure the seam gap.

    Returns:
        A single DataFrame in chronological order (empty if no segments).

    Raises:
        ValueError: If *adjust* is not one of :data:`ADJUST_METHODS`.
    """
    if adjust not in ADJUST_METHODS:
        raise ValueError("adjust must be one of %s, got %r" % (ADJUST_METHODS, adjust))

    windowed = _window_segments(segments, date_column)
    if not windowed:
        return pd.DataFrame()

    if adjust != "none" and len(windowed) >= 2:
        price_cols = [c for c in _PRICE_COLUMNS if c in windowed[0].columns]
        # Walk seams newest -> oldest so each older segment aligns to the
        # already-adjusted segment immediately after it.
        for i in range(len(windowed) - 2, -1, -1):
            older = windowed[i]
            newer_first = windowed[i + 1][price_column].iloc[0]
            older_last = older[price_column].iloc[-1]
            if adjust == "ratio":
                if older_last == 0:
                    continue
                factor = newer_first / older_last
                older[price_cols] = older[price_cols] * factor
            else:  # diff
                offset = newer_first - older_last
                older[price_cols] = older[price_cols] + offset

    return pd.concat(windowed, ignore_index=True)
