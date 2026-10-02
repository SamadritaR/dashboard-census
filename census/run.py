"""Run the census on a folder of .twb files.

Sample estate (synthetic, with usage):
  python -m census.run --workbooks sample_estate/workbooks --usage sample_estate/usage_90d.csv \
      --data sample_estate/orders.csv --out out/sample

Public corpus (real workbooks, each author treated as a team):
  python -m census.run --workbooks public_corpus/workbooks --data public_corpus/global_superstore_2016.xlsx \
      --team-from-prefix --title "62 public Tableau workbooks" --out out/public
"""
from __future__ import annotations

import argparse
import html
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from census.core import build_census, read_estate, read_usage

LABELS = {"revenue": "Revenue", "margin": "Margin", "active_customers": "Active customers",
          "order_count": "Order count", "days_to_ship": "Days to ship"}


def label(intent: str) -> str:
    return LABELS.get(intent, intent.replace("_", " ").capitalize())


def fmt(intent: str, v: float | None) -> str:
    if v is None:
        return "not priced"
    if abs(v) >= 1e5:
        return f"{v:,.0f}" if intent != "revenue" else f"${v:,.0f}"
    if intent == "margin" and abs(v) < 1.5:
        return f"{v * 100:.1f}%"
    if intent == "revenue":
        return f"${v:,.0f}"
    return f"{v:,.2f}" if v != int(v) else f"{v:,.0f}"


def gap_text(g: float | None) -> str:
    if g is None:
        return "gap not priced"
    if g >= 1000:
        return f"{g / 100 + 1:,.0f}× apart"
    return f"{g:,.1f}% apart" if g < 10 else f"{g:,.0f}% apart"


def load_data(path: Path | None) -> pd.DataFrame | None:
    if path is None:
        return None
    if path.suffix.lower() in (".xlsx", ".xls"):
        x = pd.ExcelFile(path)
        df = x.parse(x.sheet_names[0])
        if "Returns" in x.sheet_names:  # Superstore keeps returns on their own sheet
            r = x.parse("Returns")[["Order ID", "Returned"]].drop_duplicates("Order ID")
            df = df.merge(r, on="Order ID", how="left").fillna({"Returned": "No"})
        return df
    return pd.read_csv(path)


def write_context_yaml(census: dict, path: Path) -> None:
    defs = []
    for a in census["agreed"]:
        v = a["variant"]
        defs.append({"name": a["intent"], "status": "agreed", "formula": v.display,
                     "used_by": sorted({f"{c.team}: {c.workbook}" for c in v.calcs})})
    for c in census["conflicts"]:
        defs.append({"name": c["intent"], "status": "needs_decision", "decision_owner": None,
                     "gap_pct": None if c["gap_pct"] is None else round(c["gap_pct"], 1),
                     "candidates": [{"formula": v.display, "aggregation": v.aggregation, "teams": v.teams,
                                     "value": None if v.value is None else round(v.value, 4),
                                     **({"not_priced": v.note} if v.note else {})} for v in c["variants"]]})
    path.write_text(yaml.safe_dump({"generated": str(date.today()), "definitions": defs},
                                   sort_keys=False, width=110, allow_unicode=True))


def write_queue_csv(census: dict, path: Path) -> None:
    rows = [{"rank": i, "intent": c["intent"], "gap_pct": c["gap_pct"], "exposure": c["exposure"],
             "formula": v.display, "aggregation": v.aggregation, "teams": "; ".join(v.teams),
             "value": v.value, "not_priced": v.note}
            for i, c in enumerate(census["conflicts"], 1) for v in c["variants"]]
    pd.DataFrame(rows).to_csv(path, index=False)


CSS = """:root{--bg:#F5F4EF;--card:#fff;--ink:#17152E;--muted:#5D5A70;--line:#DEDBEA;--accent:#4A3FD0;--warn:#FBE7C2;--warnink:#6B4A0B;
box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#17152E;--card:#242145;--ink:#F5F4EF;--muted:#B8B4CC;--line:#3A3666;--accent:#B3ADFF;--warn:#4A3A14;--warnink:#F6D58E}}
:root[data-theme="dark"]{--bg:#17152E;--card:#242145;--ink:#F5F4EF;--muted:#B8B4CC;--line:#3A3666;--accent:#B3ADFF;--warn:#4A3A14;--warnink:#F6D58E}
html{scroll-padding-top:env(safe-area-inset-top,0px)}
body{background:var(--bg);color:var(--ink);font:16px/1.5 Inter,system-ui,Arial,sans-serif;max-width:1000px;padding:32px 20px 64px;margin:0 auto}
h1{font:400 clamp(28px,5vw,44px)/1.1 Georgia,serif;margin:8px 0 4px} h2{font-size:20px;margin:40px 0 12px} h3{margin:0;font-size:20px}
.sub{color:var(--muted)} .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:24px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px} .kpi b{display:block;font:400 32px Georgia,serif;color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin:16px 0}
.cardhead{display:flex;flex-wrap:wrap;gap:10px;align-items:center} .rank{color:var(--accent);font-weight:700}
.pill{background:var(--warn);color:var(--warnink);border-radius:99px;padding:3px 12px;font-size:14px}
.scroll{overflow-x:auto} table{border-collapse:collapse;width:100%;margin-top:12px;font-size:14.5px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top} th{color:var(--muted);font-weight:600}
td.num{white-space:nowrap;font-weight:600} code{font-size:13px;word-break:break-word} .why{color:var(--muted);font-size:13px}
.ask{margin:12px 0 0;color:var(--muted)} ul{padding-left:20px} .note{font-size:14px;color:var(--muted);border-top:1px solid var(--line);padding-top:16px;margin-top:40px}"""


def write_report(census: dict, path: Path, title: str, subtitle: str, note: str) -> None:
    e = html.escape
    cards = []
    for rank, c in enumerate(census["conflicts"], 1):
        gap = gap_text(c["gap_pct"])
        rows = "".join(
            f"<tr><td>{e(', '.join(v.teams))}</td><td><code>{e(v.display)}</code>"
            f"<div class=why>Aggregation: {e(v.aggregation)}</div></td>"
            f"<td class=num>{e(fmt(c['intent'], v.value))}"
            + (f"<div class=why>{e(v.note)}</div>" if v.note else "") + "</td></tr>"
            for v in c["variants"])
        cards.append(f"""<section class=card><div class=cardhead><span class=rank>#{rank}</span><h3>{e(label(c['intent']))}</h3>
<span class=pill>{len(c['variants'])} readings · {gap} · exposure {c['exposure']:,}</span></div>
<div class=scroll><table><tr><th>Team</th><th>Formula</th><th>Value</th></tr>{rows}</table></div>
<p class=ask>Decision needed: pick one reading, or keep both under different names. Owner: <b>unassigned</b></p></section>""")
    agreed = "".join(f"<li><b>{e(label(a['intent']))}</b> <code>{e(a['variant'].formula)}</code></li>"
                     for a in census["agreed"]) or "<li>None</li>"
    kinds = census["kinds"]
    helpers = sum(v for k, v in kinds.items() if k != "metric")
    unplaced = "".join(f"<li>{e(c.caption)} <code>{e(c.formula[:120])}</code></li>" for c in census["unplaced"])
    retire = ("<h2>Retire instead of migrating (under 5 views in 90 days)</h2><ul>"
              + "".join(f"<li>{e(d)}</li>" for d in census["retire"]) + "</ul>") if census["usage_known"] else ""
    kpi4 = (f"<div class=kpi><b>{len(census['retire'])}</b>dashboards to retire</div>" if census["usage_known"]
            else f"<div class=kpi><b>{helpers}</b>helpers skipped</div>")

    path.write_text(f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(title)}</title><style>{CSS}</style></head><body>
<p class=sub>Dashboard Census · prototype by Samadrita Roy Chowdhury</p>
<h1>{e(title)}</h1><p class=sub>{e(subtitle)}</p>
<div class=kpis>
<div class=kpi><b>{census['workbooks']}</b>workbooks with calculated fields</div>
<div class=kpi><b>{census['fields']}</b>calculated fields read</div>
{kpi4}
<div class=kpi><b>{len(census['conflicts'])}</b>conflicts to decide</div>
</div>
<h2>Decision queue, ranked by gap × exposure</h2>{''.join(cards)}
<h2>Agreed, ready to seed the context layer</h2><ul>{agreed}</ul>
{retire}
<h2>Metrics the rules could not place ({len(census['unplaced'])})</h2>
<p class=sub>These go to the LLM fallback when an API key is set, or to a person. Field kinds found: {e(', '.join(f'{k} {v}' for k, v in kinds.items()))}.</p>
<ul>{unplaced}</ul>
<p class=note>{e(note)} Source: github.com/SamadritaR/dashboard-census</p>
</body></html>""")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbooks", type=Path, required=True)
    ap.add_argument("--usage", type=Path)
    ap.add_argument("--data", type=Path)
    ap.add_argument("--team-from-prefix", action="store_true", help="team = file name before the first __")
    ap.add_argument("--same-data", action="store_true", help="ignore readings built on fields the data lacks")
    ap.add_argument("--title", default="Before you migrate: what this estate disagrees about")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--out", type=Path, default=Path("out"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    usage = read_usage(a.usage)
    census = build_census(read_estate(a.workbooks, usage, a.team_from_prefix), load_data(a.data), usage, a.same_data)
    write_report(census, a.out / "census_report.html", a.title, a.subtitle, a.note)
    write_context_yaml(census, a.out / "context.yaml")
    write_queue_csv(census, a.out / "decision_queue.csv")

    print(f"{census['fields']} fields in {census['workbooks']} workbooks; kinds {census['kinds']}")
    print(f"retire {census['retire']}; agreed {[x['intent'] for x in census['agreed']]}; unplaced {len(census['unplaced'])}")
    for c in census["conflicts"]:
        gap = gap_text(c["gap_pct"])
        print(f"CONFLICT {c['intent']} gap {gap} exposure {c['exposure']}")
        for v in c["variants"]:
            print(f"   {fmt(c['intent'], v.value):>14} | {v.aggregation:<28} | {'/'.join(v.teams)} | {v.display[:70]} {v.note}")


if __name__ == "__main__":
    main()
