"""Dashboard Census core.

  read_workbook / read_estate  pull calculated fields out of Tableau .twb files
  classify                     separate real metrics from helpers (bins, constants, labels, switches)
  group_by_intent              cluster metrics that mean the same business concept
  price_variants               run competing formulas on the same rows and measure the gap
  build_census                 retire / agreed / needs a decision
"""
from __future__ import annotations

import difflib
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

DEAD_VIEWS_90D = 5
AGGS = ("SUM", "AVG", "COUNTD", "COUNT", "MIN", "MAX", "MEDIAN", "ATTR")
AGG_RE = re.compile(r"\b(" + "|".join(AGGS) + r")\s*\(", re.I)
TABLE_CALCS = ("WINDOW_", "RUNNING_", "LOOKUP", "INDEX", "RANK", "TOTAL", "SIZE", "FIRST", "LAST")


@dataclass
class Calc:
    workbook: str
    team: str
    caption: str
    formula: str            # as written, internal ids swapped for captions
    expanded: str = ""      # referenced calcs inlined, used to compare and price
    datatype: str = ""
    role: str = ""
    derivation: str = ""    # how a sheet aggregates it (column-instance), if it says
    sheets: list[str] = field(default_factory=list)
    dashboards: list[str] = field(default_factory=list)
    views_90d: int = 0
    kind: str = ""          # metric, constant, label, bin, switch, cycle
    intent: str = ""
    intent_source: str = ""  # rule, llm, none

    @property
    def has_agg(self) -> bool:
        return bool(AGG_RE.search(re.sub(r"\{[^{}]*\}", "", self.expanded or self.formula)))

    @property
    def key(self) -> str:
        agg = "" if self.has_agg else (self.derivation or "Sum")
        return normalize(self.expanded or self.formula) + "|" + agg


def normalize(formula: str) -> str:
    f = re.sub(r"//[^\n]*", "", formula)
    f = re.sub(r"\d+\.\d+", lambda m: f"{float(m.group()):.10g}", f)  # 18.39999999 == 18.40000001
    f = f.replace('"', "'")
    return re.sub(r"\s+", "", f).upper()


# 1. Read ---------------------------------------------------------------

def read_workbook(path: Path, team: str | None = None) -> list[Calc]:
    root = ET.parse(path).getroot()
    if team is None:
        team = "unknown"
        for pref in root.iter("preference"):
            if pref.get("name") == "owner.team":
                team = pref.get("value")

    calcs: dict[str, Calc] = {}
    for ds in root.iter("datasource"):
        if ds.get("name") == "Parameters":  # parameters are stored as calcs; they are inputs, not metrics
            continue
        for col in ds.findall("column"):
            calc = col.find("calculation")
            if calc is None or not calc.get("formula") or col.get("name") in calcs:
                continue
            calcs[col.get("name")] = Calc(path.name, team, col.get("caption") or col.get("name").strip("[]"),
                                          calc.get("formula"), datatype=col.get("datatype", ""),
                                          role=col.get("role", ""))
    resolve_references(calcs)

    for ws in root.iter("worksheet"):
        for dep in ws.iter("datasource-dependencies"):
            for c in dep.findall("column"):
                k = calcs.get(c.get("name"))
                if k and ws.get("name") not in k.sheets:
                    k.sheets.append(ws.get("name"))
            for ci in dep.findall("column-instance"):
                k = calcs.get(ci.get("column"))
                if k and ci.get("derivation") in ("Sum", "Avg", "Min", "Max") and not k.derivation:
                    k.derivation = ci.get("derivation")
    sheet_to_dash: dict[str, set[str]] = {}
    for dash in root.iter("dashboard"):
        for zone in dash.iter("zone"):
            if zone.get("name"):
                sheet_to_dash.setdefault(zone.get("name"), set()).add(dash.get("name"))
    for c in calcs.values():
        c.dashboards = sorted({d for s in c.sheets for d in sheet_to_dash.get(s, ())})
        c.kind = classify(c)
    return list(calcs.values())


def resolve_references(calcs: dict[str, Calc]) -> None:
    """Swap internal ids like [Calculation_123] for captions, and inline referenced calcs."""
    by_caption = {f"[{c.caption}]": k for k, c in calcs.items()}

    def target(ref: str) -> str | None:
        return ref if ref in calcs else by_caption.get(ref)

    def inline(name: str, stack: tuple) -> str:
        if name in stack:
            raise RecursionError(" > ".join(calcs[s].caption for s in stack + (name,)))

        def sub(m):
            t = target(m.group())
            return f"({inline(t, stack + (name,))})" if t and t != name else m.group()
        return re.sub(r"\[[^\[\]]+\]", sub, calcs[name].formula)

    for k, c in calcs.items():
        try:
            c.expanded = inline(k, ())
        except RecursionError as e:
            c.kind = "cycle"
            c.expanded = ""
            c.formula += f"   (circular reference: {e})"
    for c in calcs.values():
        c.formula = re.sub(r"\[[^\[\]]+\]",
                           lambda m: f"[{calcs[m.group()].caption}]" if m.group() in calcs else m.group(), c.formula)


def read_usage(usage_csv: Path | None) -> dict[str, int]:
    if not usage_csv:
        return {}
    return pd.read_csv(usage_csv).set_index("dashboard")["views_90d"].to_dict()


def read_estate(folder: Path, usage: dict[str, int], team_from_prefix: bool = False) -> list[Calc]:
    calcs = []
    for p in sorted(folder.glob("*.twb")):
        calcs += read_workbook(p, p.name.split("__")[0] if team_from_prefix else None)
    for c in calcs:
        c.views_90d = int(sum(usage.get(d, 0) for d in c.dashboards))
    return calcs


# 2. Metric or helper -----------------------------------------------------

def classify(c: Calc) -> str:
    if c.kind == "cycle":
        return "cycle"
    f = re.sub(r"//[^\n]*", "", c.formula).strip()
    if re.fullmatch(r"-?[\d.]+|\"[^\"]*\"|'[^']*'", f):
        return "constant"
    if "(bin)" in c.caption.lower() or (re.fullmatch(r"\[[^\]]+\]", f) and "bin" in c.caption.lower()):
        return "bin"
    if c.caption.lower().startswith(("tooltip", "label")):
        return "label"
    if "[Parameters]" in f and re.match(r"\s*(CASE|IF)", f, re.I):
        return "switch"
    if c.datatype in ("string", "boolean") or c.role == "dimension":
        return "label"
    return "metric"


# 3. Group by intent ------------------------------------------------------

RULES = [
    ("order_count", lambda t: "order" in t and ("count" in t or t.strip() in ("orders", "# orders"))),
    ("active_customers", lambda t: "active" in t and ("customer" in t or "user" in t)),
    ("margin", lambda t: "margin" in t or ("profit" in t and ("ratio" in t or "%" in t))),
    ("days_to_ship", lambda t: "ship" in t and ("day" in t or "time" in t)),
    ("revenue", lambda t: re.search(r"\b(rev|revenue|sales)\b", t) is not None
     and not re.search(r"\bper\b|target|forecast|above|label|-", t)),
]


VOCAB = ["profit", "margin", "ratio", "revenue", "sales", "order", "orders", "count", "customer",
         "customers", "active", "ship", "days", "time"]


def _fix_typos(caption: str) -> str:
    """'proofit%' -> 'profit %': close misspellings of core words still match the rules."""
    out = []
    for tok in re.findall(r"[a-z]+|[^a-z\s]+", caption.lower()):
        hit = difflib.get_close_matches(tok, VOCAB, n=1, cutoff=0.8) if tok.isalpha() and len(tok) > 3 else []
        out.append(hit[0] if hit else tok)
    return " ".join(out)


def rule_intent(caption: str) -> str | None:
    t = _fix_typos(caption)
    for intent, test in RULES:
        if test(t):
            return intent
    return None


def llm_intent(caption: str, formula: str, known: list[str], opener=urllib.request.urlopen) -> str | None:
    """Fallback for captions the rules cannot place (other languages, odd names). Needs ANTHROPIC_API_KEY."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    prompt = (f"A Tableau calculated field is captioned {caption!r} with formula {formula!r}. "
              f"Which business metric does it measure? Reply with one snake_case label, reusing one of "
              f"{known} if it fits, or 'helper' if it is not a business metric. Label only.")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({"model": "claude-sonnet-4-6", "max_tokens": 20,
                         "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with opener(req, timeout=30) as r:
        label = json.loads(r.read())["content"][0]["text"].strip().lower()
    label = re.sub(r"[^a-z0-9_]", "", label)
    return None if label in ("", "helper") else label


def group_by_intent(calcs: list[Calc]) -> dict[str, list[Calc]]:
    known = [i for i, _ in RULES]
    groups: dict[str, list[Calc]] = {}
    for c in calcs:
        if c.kind != "metric":
            continue
        intent, src = rule_intent(c.caption), "rule"
        if intent is None:
            intent, src = llm_intent(c.caption, c.formula, known), "llm"
        if intent is None:
            c.intent_source = "none"
            continue
        c.intent, c.intent_source = intent, src
        groups.setdefault(intent, []).append(c)
    # A field the rules missed but whose formula matches a placed one joins that group
    by_formula = {c.key: c.intent for g in groups.values() for c in g}
    for c in calcs:
        if c.kind == "metric" and c.intent_source == "none" and c.key in by_formula:
            c.intent, c.intent_source = by_formula[c.key], "formula"
            groups[c.intent].append(c)
    return groups


# 4. Price ---------------------------------------------------------------
# Covers SUM AVG COUNTD COUNT MIN MAX, IIF, ZN, ABS, YEAR, DATEDIFF('day'),
# FIXED level of detail expressions, and the aggregation Tableau applies to
# row level measures. Anything else is reported as not priced, with the reason.

class NotPriceable(Exception):
    pass


def _env(df: pd.DataFrame) -> dict:
    def datediff(part, a, b):
        if str(part).lower() != "day":
            raise NotPriceable(f"DATEDIFF part {part!r}")
        return (pd.to_datetime(pd.Series(b)) - pd.to_datetime(pd.Series(a))).dt.days.to_numpy()

    return {
        "F": {c: df[c].to_numpy() for c in df.columns},
        "SUM": lambda x: float(np.nansum(x)), "AVG": lambda x: float(np.nanmean(x)),
        "COUNTD": lambda x: float(pd.Series(x).dropna().nunique()),
        "COUNT": lambda x: float(pd.Series(x).count()),
        "MIN": lambda x: np.nanmin(x), "MAX": lambda x: np.nanmax(x),
        "IIF": lambda c, a, b: np.where(c, a, np.nan if b is None else b), "ZN": np.nan_to_num, "ABS": np.abs,
        "YEAR": lambda x: pd.to_datetime(pd.Series(x)).dt.year.to_numpy(), "DATEDIFF": datediff, "NULL": None, "NAN": np.nan,
    }


def _translate(expr: str, columns) -> str:
    expr = re.sub(r"//[^\n]*", "", expr)
    expr = re.sub(r"\b(" + "|".join(AGGS + ("IIF", "ZN", "ABS", "YEAR", "DATEDIFF")) + r")\s*\(",
                  lambda m: m.group(1).upper() + "(", expr, flags=re.I)
    missing = set(re.findall(r"\[([^\[\]]+)\]", expr)) - set(columns) - {"Parameters"}
    if missing:
        raise NotPriceable("fields not in the data: " + ", ".join(sorted(missing)))
    if re.search(r"\b(" + "|".join(TABLE_CALCS) + r")\w*\s*\(", expr, re.I):
        raise NotPriceable("table calculation, value depends on the view")
    if re.search(r"\bSCRIPT_|\bRAWSQL|\[Parameters\]", expr, re.I):
        raise NotPriceable("parameter or external script, not supported yet")
    expr = _branches(expr)
    expr = re.sub(r"\[([^\]]+)\]", lambda m: f"F[{m.group(1)!r}]", expr).replace("<>", "!=")
    return re.sub(r"(?<![<>!=])=(?!=)", "==", expr)


def _branches(expr: str) -> str:
    """IF a THEN b [ELSEIF c THEN d] [ELSE e] END and CASE x WHEN v THEN b ... END, one level deep."""
    def if_block(m):
        body = m.group(1)
        parts = re.split(r"\bELSEIF\b|\bELSE\b", body, flags=re.I)
        tail = "NULL"
        if re.search(r"\bELSE\b(?!IF)", body, re.I):
            tail = parts.pop()
        out = tail
        for part in reversed(parts):
            cond, val = re.split(r"\bTHEN\b", part, maxsplit=1, flags=re.I)
            out = f"IIF({cond.strip()}, {val.strip()}, {out.strip()})"
        return f"({out})"

    def case_block(m):
        subject, body = m.group(1), m.group(2)
        tail = "NULL"
        if re.search(r"\bELSE\b", body, re.I):
            body, tail = re.split(r"\bELSE\b", body, maxsplit=1, flags=re.I)
        out = tail.strip()
        for when in reversed(re.split(r"\bWHEN\b", body, flags=re.I)[1:]):
            val, res = re.split(r"\bTHEN\b", when, maxsplit=1, flags=re.I)
            out = f"IIF(({subject.strip()}) == ({val.strip()}), {res.strip()}, {out})"
        return f"({out})"

    if re.search(r"\bIF\b[\s\S]*\bIF\b|\bCASE\b[\s\S]*\bCASE\b", expr, re.I):
        raise NotPriceable("nested IF/CASE, not supported yet")
    expr = re.sub(r"\bCASE\b([\s\S]*?)(\bWHEN\b[\s\S]*?)\bEND\b", case_block, expr, flags=re.I)
    expr = re.sub(r"\bIF\b([\s\S]*?)\bEND\b", if_block, expr, flags=re.I)
    return expr.replace("NULL", "NAN")


def _run(code: str, df: pd.DataFrame):
    return eval(code, {"__builtins__": {}}, _env(df))


def _lod(expr: str, df: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """Replace each {FIXED dims : agg} with a precomputed per row column."""
    pat = re.compile(r"\{\s*(?:(FIXED|INCLUDE|EXCLUDE)\s*([^:{}]*?)\s*:)?\s*([^{}]*?)\s*\}", re.I)
    i = 0
    while (m := pat.search(expr)):
        kind, dims, inner = m.group(1), m.group(2), m.group(3)
        if kind and kind.upper() != "FIXED":
            raise NotPriceable(f"{kind.upper()} level of detail")
        dims = re.findall(r"\[([^\]]+)\]", dims or "")
        code = _translate(inner, df.columns)
        if dims:
            vals = df.groupby(dims, sort=False)[list(df.columns)].apply(lambda g: _run(code, g))
            col = df[dims].merge(vals.rename("_v").reset_index(), on=dims, how="left")["_v"].to_numpy()
        else:
            col = np.full(len(df), _run(code, df))
        name = f"_LOD{i}"
        i += 1
        df = df.assign(**{name: col})
        expr = expr[:m.start()] + f"[{name}]" + expr[m.end():]
    return expr, df


def evaluate(formula: str, df: pd.DataFrame, derivation: str = "") -> float:
    expr, df = _lod(formula, df)
    code = _translate(expr, df.columns)
    if not AGG_RE.search(expr):  # row level measure: Tableau aggregates it, SUM unless the sheet says otherwise
        code = f"{(derivation or 'Sum').upper()}({code})"
    return float(_run(code, df))


@dataclass
class Variant:
    formula: str
    calcs: list[Calc]
    value: float | None
    note: str = ""

    @property
    def teams(self) -> list[str]:
        return sorted({c.team for c in self.calcs})

    @property
    def views_90d(self) -> int:
        return sum(c.views_90d for c in self.calcs)

    @property
    def display(self) -> str:
        return re.sub(r"\s+", " ", re.sub(r"//[^\n]*", "", self.formula)).strip()

    @property
    def aggregation(self) -> str:
        c = self.calcs[0]
        if c.has_agg:
            return "in the formula"
        return f"{(c.derivation or 'Sum').upper()}, " + ("set on a sheet" if c.derivation else "Tableau default")


def price_variants(calcs: list[Calc], df: pd.DataFrame | None) -> list[Variant]:
    by_key: dict[str, list[Calc]] = {}
    for c in calcs:
        by_key.setdefault(c.key, []).append(c)
    out = []
    for cs in by_key.values():
        c = cs[0]
        if df is None:
            out.append(Variant(c.formula, cs, None, "no data supplied"))
            continue
        try:
            out.append(Variant(c.formula, cs, evaluate(c.expanded or c.formula, df, c.derivation)))
        except NotPriceable as e:
            out.append(Variant(c.formula, cs, None, str(e)))
    return out


# 5. Census --------------------------------------------------------------

def build_census(calcs: list[Calc], df: pd.DataFrame | None, usage: dict[str, int],
                 same_data: bool = False) -> dict:
    """same_data: drop readings built on fields this dataset does not have (they describe another source)."""
    dash_views = {d: int(usage.get(d, 0)) for c in calcs for d in c.dashboards}
    retire = sorted(d for d, v in dash_views.items() if v < DEAD_VIEWS_90D) if usage else []
    live = [c for c in calcs if not (c.dashboards and set(c.dashboards) <= set(retire))]

    agreed, conflicts, other_source = [], [], 0
    for intent, group in group_by_intent(live).items():
        variants = price_variants(group, df)
        if same_data:
            other = [v for v in variants if v.note.startswith("fields not in the data")]
            other_source += sum(len(v.calcs) for v in other)
            variants = [v for v in variants if v not in other]
        if not variants:
            continue
        if len(variants) == 1:
            agreed.append({"intent": intent, "variant": variants[0]})
            continue
        priced = sorted([v for v in variants if v.value is not None], key=lambda v: v.value)
        variants = priced + [v for v in variants if v.value is None]
        gap_pct = None
        if len(priced) > 1 and priced[0].value:
            gap_pct = abs(priced[-1].value - priced[0].value) / abs(priced[0].value) * 100
        exposure = sum(v.views_90d for v in variants) if usage else \
            sum(len(c.sheets) for v in variants for c in v.calcs)
        conflicts.append({"intent": intent, "variants": variants, "gap_pct": gap_pct, "exposure": exposure,
                          "priority": (gap_pct or 0) * max(exposure, 1)})
    conflicts.sort(key=lambda x: x["priority"], reverse=True)

    return {"workbooks": len({c.workbook for c in calcs}), "fields": len(calcs),
            "dashboards": len(dash_views), "retire": retire, "agreed": agreed, "conflicts": conflicts,
            "kinds": pd.Series([c.kind for c in calcs]).value_counts().to_dict(),
            "unplaced": [c for c in live if c.kind == "metric" and c.intent_source == "none"],
            "usage_known": bool(usage), "other_source": other_source}
