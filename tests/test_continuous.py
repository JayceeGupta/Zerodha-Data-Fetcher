"""Phase 5 — pure continuous-series stitching (no I/O)."""

from datetime import date

import pandas as pd
import pytest

from zerodha_data_fetcher.core.continuous import stitch_segments


def _seg(dates, closes):
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Close": closes,
            "Volume": [100] * len(closes),
        }
    )


def _segments():
    # Two front-month contracts. Contract A (expiry 2024-08-31) and contract B
    # (expiry 2024-09-30). Both trade in overlapping windows; stitching should
    # keep A's bars up to its expiry, then B's bars afterward.
    a = _seg(["2024-08-15", "2024-08-31", "2024-09-15"], [100, 110, 108])
    b = _seg(["2024-08-31", "2024-09-15", "2024-09-30"], [120, 130, 140])
    return [(date(2024, 8, 31), a), (date(2024, 9, 30), b)]


def test_none_windows_by_expiry_and_concatenates():
    result = stitch_segments(_segments(), adjust="none")

    # A contributes bars up to its expiry (Aug 15, Aug 31); B contributes the
    # bars after A's expiry (Sep 15, Sep 30). No fabricated prices.
    assert result["Close"].tolist() == [100, 110, 130, 140]
    assert result["Date"].tolist() == [
        "2024-08-15",
        "2024-08-31",
        "2024-09-15",
        "2024-09-30",
    ]


def test_diff_back_adjust_makes_series_continuous_at_seam():
    result = stitch_segments(_segments(), adjust="diff")
    closes = result["Close"].tolist()

    # Newest segment (B) is the anchor — unchanged: last two are 130, 140.
    assert closes[-2:] == [130, 140]
    # Seam continuity: older segment shifted so its last bar meets B's first
    # windowed bar (130). Offset = 130 - 110 = 20, applied to A's bars.
    assert closes[:2] == [120, 130]


def test_ratio_back_adjust_scales_older_segment():
    result = stitch_segments(_segments(), adjust="ratio")
    closes = result["Close"].tolist()

    assert closes[-2:] == [130, 140]
    # factor = 130 / 110; A's closes 100,110 -> 100*f, 110*f (=130).
    factor = 130 / 110
    assert closes[0] == pytest.approx(100 * factor)
    assert closes[1] == pytest.approx(130)


def test_single_segment_passthrough():
    a = _seg(["2024-08-15", "2024-08-31"], [100, 110])
    result = stitch_segments([(date(2024, 8, 31), a)], adjust="ratio")
    assert result["Close"].tolist() == [100, 110]


def test_empty_segments_returns_empty_frame():
    assert stitch_segments([], adjust="none").empty


def test_unknown_adjust_raises():
    with pytest.raises(ValueError):
        stitch_segments(_segments(), adjust="panama")
