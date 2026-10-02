import io
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from census.core import Calc, classify, evaluate, llm_intent, read_workbook, rule_intent

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "public_corpus" / "workbooks"
needs_corpus = pytest.mark.skipif(not CORPUS.exists(), reason="run public_corpus/fetch_corpus.py first")


def test_evaluator_basics():
    df = pd.DataFrame({"Sales": [100.0, 50.0], "Discount": [0.1, 0.0], "Returned": ["No", "Yes"]})
    assert evaluate("SUM([Sales])", df) == 150
    assert evaluate("SUM([Sales] * (1 - [Discount]))", df) == 140
    assert evaluate('SUM(IIF([Returned] = "Yes", 0, [Sales]))', df) == 100


def test_row_level_measure_uses_sheet_aggregation():
    df = pd.DataFrame({"Profit": [10.0, -40.0], "Sales": [100.0, 50.0]})
    assert evaluate("[Profit]/[Sales]", df, "Avg") == evaluate("AVG([Profit]/[Sales])", df)
    assert evaluate("[Profit]/[Sales]", df) == evaluate("SUM([Profit]/[Sales])", df)  # Tableau default


def test_fixed_lod():
    df = pd.DataFrame({"Customer ID": ["a", "a", "b"], "Order ID": ["1", "2", "3"]})
    # each row carries its customer's order count, then Tableau sums the rows
    assert evaluate("{FIXED [Customer ID]:COUNTD([Order ID])}", df) == 2 + 2 + 1


def test_if_and_case():
    df = pd.DataFrame({"Profit": [5.0, -3.0], "Ship Mode": ["Same Day", "Standard Class"]})
    assert evaluate("SUM(IF [Profit] > 0 THEN [Profit] ELSE 0 END)", df) == 5
    assert evaluate('SUM(CASE [Ship Mode] WHEN "Same Day" THEN 0 WHEN "Standard Class" THEN 6 END)', df) == 6


def test_rules_and_typos():
    assert rule_intent("Rev excl Returns") == "revenue"
    assert rule_intent("proofit%") == "margin"  # real caption from a public workbook
    assert rule_intent("ORDERS COUNT") == "order_count"
    assert rule_intent("Sales per Customer") is None


def test_helpers_are_not_metrics():
    assert classify(Calc("w", "t", "Top Customers", "5")) == "constant"
    assert classify(Calc("w", "t", "Profit (bin)", "[Profit]")) == "bin"
    assert classify(Calc("w", "t", "Zone Sales", 'CASE [Parameters].[P1] WHEN "EU" THEN [EU] END')) == "switch"


@needs_corpus
def test_real_workbook_cycle_is_caught_not_crashed():
    calcs = read_workbook(CORPUS / "PrigasG__twbparser__rebuild_kit.twb")
    assert {c.caption for c in calcs if c.kind == "cycle"} == {"Cycle A", "Cycle B"}


@needs_corpus
def test_parameters_are_skipped():
    calcs = read_workbook(CORPUS / "tableau__document-api-python__geocoding.twb")
    assert "Commission Rate" not in {c.caption for c in calcs}


def test_llm_fallback_contract(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    sent = {}

    def fake_open(req, timeout):
        sent["body"] = json.loads(req.data)
        return Resp(json.dumps({"content": [{"text": "margin"}]}).encode())

    assert llm_intent("%ประเทศ", "SUM([x])/TOTAL(SUM([x]))", ["margin"], fake_open) == "margin"
    assert "%ประเทศ" in sent["body"]["messages"][0]["content"]
