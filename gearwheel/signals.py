"""
The gear: which of the semester's two strategies runs tomorrow.

One function, used by both the backtest (gearwheel/backtest.py) and the
nightly order writer (gearwheel/orders.py), so the rule that was tested is
the rule that trades.

    hold    the close is above its 200-session average (an uptrend) AND the
            21-session realised vol is at or below its own median over the
            past 252 sessions (a calm one). Own the shares, sell nothing:
            short calls capped every rally this semester (1.2, 1.3, 2023 in
            1.4).
    wheel   anything else. 1.4's rule: cash-secured puts, assignment, calls
            at or above the basis. The wheel lost 8% in 2022 while the stock
            lost 28%.

Both thresholds are the textbook ones, fixed before any backtest was run;
neither was tuned. Until there is enough history for both (about 470
sessions), the gear is "wheel".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MA = 200            # sessions in the trend average
RV = 21             # sessions in the realised-vol window
LOOKBACK = 252      # sessions over which "calm" is judged


def gears(close: pd.Series) -> pd.DataFrame:
    """Per session, using closes up to and including that session only."""
    c = pd.to_numeric(close, errors="coerce").dropna().sort_index()
    c = c[~c.index.duplicated(keep="last")]
    sma = c.rolling(MA).mean()
    rv = np.log(c).diff().rolling(RV).std(ddof=1) * np.sqrt(252) * 100
    med = rv.rolling(LOOKBACK).median()
    up = c > sma
    calm = rv <= med
    ready = sma.notna() & med.notna()
    out = pd.DataFrame({"close": c, "sma": sma, "rv": rv, "rv_median": med,
                        "up": up & ready, "calm": calm & ready})
    out["gear"] = np.where(ready & up & calm, "hold", "wheel")
    return out


def gear_map(close: pd.Series) -> dict:
    """{date: gear} for wheel.book.run."""
    g = gears(close)
    return {t.date(): v for t, v in g["gear"].items()}
