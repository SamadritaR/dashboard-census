"""Builds a small synthetic Tableau estate for testing Dashboard Census.

Everything here is invented: the orders data, the six workbooks, and the
usage log. Conflicts are planted on purpose so the census has something
to find. Run once: python sample_estate/make_estate.py
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
rng = np.random.default_rng(7)

# Orders: trailing 12 months, one row per order line
n = 6000
sales = np.round(rng.gamma(2.0, 120.0, n), 2)
discount = rng.choice([0, 0, 0, 0.1, 0.2, 0.3, 0.5], n)
profit = np.round(sales * (0.28 - discount * 0.9) + rng.normal(0, 18, n), 2)
orders = pd.DataFrame({
    "Order ID": [f"O{100000 + i}" for i in range(n)],
    "Customer ID": [f"C{c}" for c in rng.integers(1, 1400, n)],
    "Region": rng.choice(["West", "East", "Central", "South"], n),
    "Sales": sales,
    "Discount": discount,
    "Profit": profit,
    "Returned": rng.choice(["No"] * 12 + ["Yes"], n),
    "Days Since Order": rng.integers(0, 365, n),
})
orders.to_csv(ROOT / "orders.csv", index=False)

# Workbooks: (file, team, dashboard, [(caption, formula)])
WORKBOOKS = [
    ("finance_board_pack.twb", "Finance", "Board Pack", [
        ("Net Revenue", "SUM([Sales] * (1 - [Discount]))"),
        ("Profit Margin", "SUM([Profit]) / SUM([Sales])"),
        ("Orders", "COUNTD([Order ID])"),
    ]),
    ("sales_weekly.twb", "Sales", "Weekly Sales", [
        ("Revenue", "SUM([Sales])"),
        ("Active Customers", "COUNTD(IIF([Days Since Order] <= 90, [Customer ID], NULL))"),
        ("Order Count", "COUNTD([Order ID])"),
    ]),
    ("marketing_growth.twb", "Marketing", "Growth Overview", [
        ("Total Revenue", "SUM([Sales])"),
        ("Active Customers", "COUNTD(IIF([Days Since Order] <= 30, [Customer ID], NULL))"),
        ("Margin %", "AVG([Profit] / [Sales])"),
    ]),
    ("ops_returns.twb", "Operations", "Returns Watch", [
        ("Rev excl Returns", "SUM(IIF([Returned] = \"Yes\", 0, [Sales]))"),
    ]),
    ("region_review_2023.twb", "Sales", "Region Review 2023", [
        ("Revenue", "SUM([Sales])"),
    ]),
    ("exec_kpis_old.twb", "Strategy", "Exec KPIs (old)", [
        ("Profit Ratio", "SUM([Profit]) / SUM([Sales])"),
    ]),
]
USAGE = {"Board Pack": 410, "Weekly Sales": 1250, "Growth Overview": 640,
         "Returns Watch": 95, "Region Review 2023": 0, "Exec KPIs (old)": 3}


def xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


(ROOT / "workbooks").mkdir(exist_ok=True)
calc_id = 1000
for fname, team, dash, calcs in WORKBOOKS:
    cols, deps = [], []
    for caption, formula in calcs:
        calc_id += 1
        name = f"[Calculation_{calc_id}]"
        cols.append(
            f"      <column caption='{caption}' datatype='real' name='{name}' role='measure' type='quantitative'>\n"
            f"        <calculation class='tableau' formula=\"{xml_escape(formula)}\" />\n"
            f"      </column>")
        deps.append(f"          <column name='{name}' />")
    sheet = f"{dash} detail"
    twb = f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook source-build='2024.2.0' version='18.1'>
  <repository-location id='{fname[:-4]}' site='acme' />
  <preferences><preference name='owner.team' value='{team}' /></preferences>
  <datasources>
    <datasource caption='Orders' name='federated.orders' inline='true'>
{chr(10).join(cols)}
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='{sheet}'>
      <table><view>
        <datasource-dependencies datasource='federated.orders'>
{chr(10).join(deps)}
        </datasource-dependencies>
      </view></table>
    </worksheet>
  </worksheets>
  <dashboards>
    <dashboard name='{dash}'><zones><zone name='{sheet}' /></zones></dashboard>
  </dashboards>
</workbook>
"""
    (ROOT / "workbooks" / fname).write_text(twb)

pd.DataFrame([{"dashboard": d, "views_90d": v} for d, v in USAGE.items()]).to_csv(
    ROOT / "usage_90d.csv", index=False)
print("estate written:", len(WORKBOOKS), "workbooks,", n, "order lines")
