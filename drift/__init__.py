"""Earnings-surprise drift: the final project's investment thesis.

    snapshot.py  the research pull (LSEG, Nov 2026) cut down to two files
                 in drift/data/: every top-20 report since 2022 and the daily
                 bars the trades need
    core.py      the rule, shared by the backtest and the nightly tracker
    tracker.py   nightly: new bars, new reports, their option-implied moves
                 -> docs/drift/tracker.json (the page's chart and status)
"""
