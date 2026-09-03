# Assignment 1.1 — Option Surface Lab

Transcribed from Canvas on 2026-09-03. This supersedes the README that shipped
in the assignment .zip, which carried stale instructions and the wrong field
name. Due **Monday 2026-09-08, 11:59pm** (moved back from Sep 04).

From the instructors' note:

- You do not have to use Reflex; implementation details are up to you.
- Use GitHub Pages to publish your app. Some app functionality will be lost by
  publishing statically — that is expected.
- Reference example: https://jakevestal.github.io/535_fintech/

---

This is the first layer of an app that will keep growing all semester. Every
homework adds something to the same site.

The job this week is options data — including expired contracts — plus the
workflow you will use for the rest of the course.

> **What you are actually going to discover:** options data is sparse. Many of
> the contracts you want have no price on the day you want it for the strike
> you want. That is the nature of the instrument. Simulating a realistic fill
> on an option that barely trades requires the volatility surface, which is
> next week. This week you only need to *see* the holes.

## Learning objectives

- Pull and cache historical prices for expired option contracts.
- Treat options data as sparse and misleading, not as a filled sheet.
- Build an interactive app with charts and widget switches.
- See, concretely, where the data runs out.

## What to turn in

A link to your GitHub Pages hosted site containing a working version of your
app. Serve it as an HTML file, or deploy the frontend portion of your app —
your choice, but the HTML file is probably simplest.

Your app must:

1. Load the cached LSEG pickle containing your fetched data.
2. Parse each RIC into `{underlying, expiry, put/call, strike}` and a tidy long
   table: one row per contract per date.
3. Show a 3D figure of puts or calls for one as-of date.
4. Plot **both** `MID_PRICE` and `TRDPRC_1` so a stranger can see they are not
   the same series.
5. Print two numbers on the page:
   - percent of listed series that day with a mid and **no** trade
   - median `|MID_PRICE − TRDPRC_1|` on series that have both
6. Change the colour scheme and format into a graphical identity you like.

Write three sentences under the plot:

- Where is the cloud of price data dense, and where is it empty?
- Why is interpolating across empty cells dangerous on a $0.50 strike grid for
  a name like UUUU?
- Which field will you treat as the mark next week, and which field will you
  treat as evidence that someone traded?

## The two prices you are not allowed to confuse

- `TRDPRC_1` — last **trade** on that RIC that day. Missing on most listed
  strikes. When it exists it is one print, not a mark.
- `MID_PRICE` — the closing NBBO midpoint, `(bid + ask) / 2` at the exchange
  close. LSEG does not expose a true exchange settlement price for expired US
  equity options (the `SETTLE` field returns "universe does not support" on
  this RIC space, and `TR.SettlementPrice` comes back empty), so `MID_PRICE` is
  the closest mark-of-the-close we get. Exists on far more series than trades.
  On a name that barely trades it is still a mid of a possibly-stale quote.

If you feed `TRDPRC_1` into a surface and then read prices off the holes, you
are pricing off prints that did not happen.

## Parse the RICs

```
{ROOT}{M}{DD}{YY}{SSSSS}.U^{M}{YY}
```

| Element | Meaning |
|---|---|
| `ROOT` | Underlying root, uppercase (e.g. `UUUU`) |
| `M` | Month letter: `A–L` = Jan–Dec **calls**; `M–X` = Jan–Dec **puts** |
| `DD` | Two-digit expiration day |
| `YY` | Two-digit year |
| `SSSSS` | Strike × 100, zero-padded to five digits (`$12.50` → `01250`) |
| `.U` | Exchange / venue qualifier |
| `^{M}{YY}` | Expired-contract suffix; repeats the month letter and year |

Example: `UUUUA1502601250.U^A26` is the UUUU 15-Jan-2026 **call** struck at
$12.50.

> **This appendix is wrong for puts.** The suffix does not repeat the put
> month letter — it uses the call code for that expiry chain. See `ric.py`.

Synthetic construction means many of the RICs you generate never existed.
Request in batches, tolerate failures, fall back to single RICs when a batch
throws.

## Three things to be aware of

- A candidate is generated for every Friday in the window. If your name only
  lists monthlies, most come back empty. That is expected.
- If the underlying split inside your window, the synthetic RICs will not find
  the adjusted contracts. Check. If it split, pick something else.
- Taking the high and low across the entire window and generating every strike
  in between for every expiry makes the pull crawl. Banding strikes per expiry
  cuts the request count a lot.

## Appendix — OPRA month codes

| Month | Call | Put |  | Month | Call | Put |
|---|---|---|---|---|---|---|
| Jan | A | M |  | Jul | G | S |
| Feb | B | N |  | Aug | H | T |
| Mar | C | O |  | Sep | I | U |
| Apr | D | P |  | Oct | J | V |
| May | E | Q |  | Nov | K | W |
| Jun | F | R |  | Dec | L | X |
