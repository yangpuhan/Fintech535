"""
OPRA-style RICs for expired US equity options — the 1.2 revision.

Assignment 1.1 established the body/suffix split::

    {ROOT}{M}{DD}{YY}{SSSSS}.U^{M}{YY}

and one correction: the ``^`` suffix names the expiry *chain*, which is
keyed off the **call** month code whatever the contract's own right is.
That still holds, and this module keeps it.

A second correction, found on AAPL this week
--------------------------------------------
The 1.2 brief says "DAY not zero-padded" and offers two single-digit
examples. Neither resolves::

    AAPLH72633000.U^H26    bare day    -> TS.Interday...70005, universe not found
    AAPLH072633000.U^H26   padded day  -> resolves

The brief's one sample that *does* resolve, ``AAPLG172620000.U^G26``, has a
two-digit day, so it cannot distinguish the two conventions. Every
single-digit Friday in this window (7 Aug, 4 Sep) needs the pad. Follow the
appendix literally and you silently lose those two weeks — and losing a week
of a weekly-option backtest is not a cosmetic bug, it is two missing trades.

So: day is always two digits, zero-padded.
"""

from __future__ import annotations

import datetime as dt
import re

# A-L are calls Jan-Dec, M-X are puts Jan-Dec.
CALL_CODES = {chr(ord("A") + i): i + 1 for i in range(12)}
PUT_CODES = {chr(ord("M") + i): i + 1 for i in range(12)}
CODE_TO_MONTH = {**CALL_CODES, **PUT_CODES}
CODE_TO_RIGHT = {**{c: "C" for c in CALL_CODES}, **{c: "P" for c in PUT_CODES}}

PATTERN = re.compile(
    r"^(?P<root>[A-Z]+)"
    r"(?P<code>[A-X])"
    r"(?P<day>\d{2})"
    r"(?P<year>\d{2})"
    r"(?P<strike>\d{5})"
    r"(?:\.U)?"
    r"(?:\^[A-X]\d{2})?$",
    re.IGNORECASE,
)


def month_code(month: int, right: str) -> str:
    """Month letter for a right: A-L for calls, M-X for puts."""
    if right not in ("C", "P"):
        raise ValueError(f"right must be 'C' or 'P', got {right!r}")
    base = "A" if right == "C" else "M"
    return chr(ord(base) + month - 1)


def build_option_ric(root: str, expiry: dt.date, strike: float, right: str) -> str:
    """
    Compose an expired-contract RIC.

    Body carries the contract's own month code and a zero-padded day; the
    suffix carries the expiry chain's code, which is always the call code.
    """
    if not 0 < strike < 1000:
        # strike x 100 has to land in five digits, so $1000+ names need a
        # different encoding than this one. Refuse rather than truncate.
        raise ValueError(f"strike {strike} outside the five-digit encoding")
    body = month_code(expiry.month, right)
    chain = month_code(expiry.month, "C")
    strike_code = f"{int(round(strike * 100)):05d}"
    return f"{root.upper()}{body}{expiry:%d}{expiry:%y}{strike_code}.U^{chain}{expiry:%y}"


def parse_option_ric(ric: str) -> dict | None:
    """Decompose a RIC into ``{underlying, expiry, right, strike}``, or None."""
    text = str(ric).strip()
    m = PATTERN.match(text)
    if not m:
        return None

    code = m.group("code").upper()
    month = CODE_TO_MONTH.get(code)
    right = CODE_TO_RIGHT.get(code)
    if month is None or right is None:
        return None
    try:
        expiry = dt.date(2000 + int(m.group("year")), month, int(m.group("day")))
    except ValueError:
        return None

    return {
        "ric": text,
        "underlying": m.group("root").upper(),
        "expiry": expiry,
        "right": right,
        "strike": int(m.group("strike")) / 100.0,
    }
