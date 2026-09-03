"""
OPRA-style RICs for expired US equity options.

Appendix A of the brief::

    {ROOT}{M}{DD}{YY}{SSSSS}.U^{M}{YY}

    ROOT    underlying root, uppercase          UUUU
    M       month letter: A-L calls Jan-Dec,    A = Jan call
            M-X puts Jan-Dec                    M = Jan put
    DD      two-digit expiration day            15
    YY      two-digit year                      26
    SSSSS   strike x 100, zero-padded to five   01250 = $12.50
    .U      exchange / venue qualifier
    ^{M}{YY} expired-contract suffix

    UUUUA1502601250.U^A26  ->  UUUU 15-Jan-2026 call struck at $12.50

One correction to the appendix
------------------------------
It says the suffix "repeats the month letter". That holds for calls and not
for puts. Following it literally returns
``TS.Interday.UserRequestError.70005, The universe is not found`` on every
put in the window::

    UUUUT212601500.U^T26   put code in the suffix    -> not found
    UUUUT212601500.U^H26   call code in the suffix   -> resolves

The suffix names the expiry *chain*, and the chain is keyed off the call
code whatever the contract's own right happens to be. Get this wrong and the
put half of the pull comes back silently empty — no error, just no data.
"""

from __future__ import annotations

import datetime as dt
import re

# A-L are calls Jan-Dec, M-X are puts Jan-Dec.
CALL_CODES = {chr(ord("A") + i): i + 1 for i in range(12)}
PUT_CODES = {chr(ord("M") + i): i + 1 for i in range(12)}
CODE_TO_MONTH = {**CALL_CODES, **PUT_CODES}
CODE_TO_RIGHT = {**{c: "C" for c in CALL_CODES}, **{c: "P" for c in PUT_CODES}}

# The suffix is tolerated but never trusted — the body carries the right.
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

    The body carries the contract's own month code; the suffix carries the
    expiry chain's, which is always the call code. See the module docstring.
    """
    body = month_code(expiry.month, right)
    chain = month_code(expiry.month, "C")
    strike_code = f"{int(round(strike * 100)):05d}"
    return f"{root.upper()}{body}{expiry:%d}{expiry:%y}{strike_code}.U^{chain}{expiry:%y}"


def parse_option_ric(ric: str) -> dict | None:
    """
    Decompose a RIC into ``{underlying, expiry, right, strike}``.

    Returns None for anything that is not an option RIC, so callers can feed
    it a whole column index without filtering first.
    """
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
        # e.g. a "31" day on a 30-day month — not a real contract
        return None

    return {
        "ric": text,
        "underlying": m.group("root").upper(),
        "expiry": expiry,
        "right": right,
        "strike": int(m.group("strike")) / 100.0,
    }
