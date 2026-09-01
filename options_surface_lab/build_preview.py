"""
Standalone HTML preview — every figure, no Reflex, no dev server.

Useful for the checkpoint demo (open the file, it just works) and for
checking a styling change without waiting on a frontend rebuild.

    python -m options_surface_lab.build_preview
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .option_surface_plots import (
    candlestick_figure,
    mark_vs_print_figure,
    occupancy_figure,
    price_surface_figure,
    spread_figure,
)
from .option_surface_theme import (
    CARD,
    INK,
    INK_MUTED,
    MARK,
    MARK_FIELD,
    MONO,
    PAPER,
    PRINT,
    PRINT_FIELD,
    RULE,
    SERIF,
    FONT_URL,
)
from .option_surface_utils import (
    grid_occupancy,
    load_payload,
    prepare,
    summarize_sparsity,
)

OUT = Path(__file__).with_name("options_surface_preview.html")


def _card(label: str, value, hint: str = "", accent: str = INK) -> str:
    return (
        f"<div style='background:{CARD};border:1px solid {RULE};border-radius:4px;"
        "padding:14px 18px;min-width:190px;flex:1 1 190px;'>"
        f"<div style='font-family:{MONO};font-size:11px;color:{INK_MUTED};"
        "letter-spacing:.08em;text-transform:uppercase;'>{}</div>".format(label)
        + f"<div style='font-family:{SERIF};font-size:30px;font-weight:700;color:{accent};"
        f"line-height:1.15;margin-top:5px;'>{value}</div>"
        + (f"<div style='font-family:{SERIF};font-size:12px;color:{INK_MUTED};"
           f"margin-top:3px;'>{hint}</div>" if hint else "")
        + "</div>"
    )


def main() -> Path:
    payload = load_payload()
    wide = prepare(payload)
    ticker = payload.get("ticker", "UUUU")

    # busiest session makes the best still image
    asof = wide.groupby(wide["date"].dt.strftime("%Y-%m-%d")).size().idxmax()
    cp = "C"
    day = wide[(wide["date"] == pd.Timestamp(asof)) & (wide["cp"] == cp)]
    stats = summarize_sparsity(day)
    occ = grid_occupancy(wide, asof, cp)

    med = stats["median_abs_diff"]
    med_txt = "n/a" if med is None else f"${med:.3f}"
    spread_txt = "n/a" if stats["median_spread"] is None else f"${stats['median_spread']:.2f}"

    header = f"""
    <div style="max-width:1180px;margin:0 auto;padding:40px 24px 0;">
      <div style="font-family:{MONO};font-size:11px;color:{INK_MUTED};letter-spacing:.1em;">
        MENG FINTECH · ALGORITHMIC TRADING II · ASSIGNMENT 1.1
      </div>
      <h1 style="font-family:{SERIF};font-size:44px;color:{INK};margin:6px 0 0;font-weight:700;">
        Options Surface Lab
      </h1>
      <p style="font-family:{SERIF};font-size:17px;color:{INK_MUTED};max-width:60ch;
                line-height:1.55;margin:10px 0 0;">
        Listed options are a sparse cloud, not a filled sheet.
        This page is arranged so the holes show up first.
      </p>
      <div style="font-family:{MONO};font-size:12px;color:{INK_MUTED};margin:18px 0 6px;">
        {ticker} · as-of {asof} · {'SYNTHETIC panel' if payload.get('synthetic')
          else f"LSEG pull cached {payload.get('fetched_at', '?')}"}
        · {wide['ric'].nunique()} expired contracts
      </div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;margin:14px 0 8px;">
        {_card('marked, never traded', f"{stats['pct_mark_no_print']:.0f}%",
               'of contracts with a mark, share with no print', PRINT)}
        {_card('median |mark − trade|', med_txt, 'on contracts that have both', MARK)}
        {_card('listed grid never traded', f"{occ['pct_never_traded']:.0f}%",
               f"of {occ['cells']} listed cells", PRINT)}
        {_card('nothing quoted at all', f"{occ['pct_empty']:.0f}%", 'not even a mark')}
        {_card('contracts marked', stats['n_mark'], 'vs traded →')}
        {_card('contracts traded', stats['n_print'], 'someone really paid this')}
        {_card('median bid/ask', spread_txt, "the width you'd actually pay")}
      </div>
    </div>
    """

    figures = [
        ("Where the data is not",
         "One cell per listed (expiry, strike). Grey was listed and never quoted. "
         "Blue carries a model mark nobody traded. Only red is a real transaction.",
         occupancy_figure(wide, asof, cp, ticker)),
        ("The cloud in three dimensions",
         "Strike across, days to expiry into the page, price up. The pale sheet is "
         "linear interpolation — an assumption, not a market.",
         price_surface_figure(wide, asof, cp=cp, show_interpolated=True, ticker=ticker)),
        ("The mark is not the trade",
         "If the two fields were the same number, every point would sit on the dashed line.",
         mark_vs_print_figure(wide, asof, cp, ticker)),
        ("So what would you actually get filled at?",
         "A range, not a number. Where the bid drops to zero there is nobody on the other side.",
         spread_figure(wide, asof, cp, ticker)),
        ("The underlying, for reference", "", candlestick_figure(payload.get("stock"), ticker)),
    ]

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Options Surface Lab · UUUU</title>",
        f"<link rel='stylesheet' href='{FONT_URL}'>",
        f"<style>body{{margin:0;background:{PAPER};}}"
        f".sec{{max-width:1180px;margin:0 auto;padding:28px 24px 0;}}"
        f".sec h2{{font-family:{SERIF};font-size:24px;color:{INK};margin:0;font-weight:700;}}"
        f".sec p{{font-family:{SERIF};font-size:15px;color:{INK_MUTED};max-width:62ch;"
        f"line-height:1.55;margin:6px 0 14px;}}"
        f".fig{{max-width:1180px;margin:0 auto 8px;padding:0 24px;}}"
        f".fig>div{{background:{CARD};border:1px solid {RULE};border-radius:4px;padding:14px;}}"
        "</style></head><body>",
        header,
    ]
    first = True
    for title, blurb, fig in figures:
        parts.append(f"<div class='sec'><h2>{title}</h2>"
                     + (f"<p>{blurb}</p>" if blurb else "<div style='height:14px'></div>")
                     + "</div>")
        parts.append("<div class='fig'><div>"
                     + fig.to_html(full_html=False,
                                   include_plotlyjs="cdn" if first else False)
                     + "</div></div>")
        first = False

    parts.append(
        f"<div class='sec' style='padding-bottom:48px;'>"
        f"<p style='font-family:{MONO};font-size:12px;border-top:1px solid {RULE};"
        f"padding-top:14px;'>mark = {MARK_FIELD} · print = {PRINT_FIELD} · "
        "SETTLE is not offered on this universe</p></div>"
    )
    parts.append("</body></html>")

    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"  as-of {asof} · {stats['n_mark']} marked / {stats['n_print']} traded "
          f"· {stats['pct_mark_no_print']:.0f}% marked-never-traded · {occ['pct_empty']:.0f}% grid empty")
    return OUT


if __name__ == "__main__":
    main()
