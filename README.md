# Dashboard Census

Before a company moves its Tableau dashboards into an AI analytics platform, find out what those dashboards disagree about.

**[Open the live dashboard →][(https://samadritar.github.io/dashboard-census/)*

An interactive view of both runs: the ranked decision queue, why each metric disagrees, and a click to pick the agreed definition and see what the AI analyst's context gets.

Tableau keeps business logic inside each workbook, so every team quietly writes its own "margin." Migrate the estate as is and those conflicts land in the context layer all at once, after users are already getting answers. The census sorts them out first: it reads every calculated field, groups the ones that mean the same thing, prices how far apart they land on real rows, and ranks the decisions an owner has to make.

Built as a proposal for [WisdomAI](https://wisdom.ai). It extends my [Greenroom deal capture](https://github.com/SamadritaR/greenroom-starter) case study, where the lesson was the same: disputes are born when terms are captured, so catch them there.

## Result 1: 62 real public workbooks

Workbooks published on GitHub by 19 authors, each author treated as a team, priced on the real Global Superstore data (51,290 order lines).

| Concept | What the census found | Gap |
|---|---|---|
| Margin | Five authors use `SUM([Profit]) / SUM([Sales])` = 11.6%. One sales dashboard also carries `[Profit]/[Sales] * 100`, which Tableau sums by default: 243,266. | about 2 million times |
| Days to ship | The same `DATEDIFF` formula is averaged on one author's sheet (3.97 days) and summed on two others (203,589). The formula matches; the meaning lives in the sheet. A separate "scheduled" version by ship mode collides on the name. | about 56,000 times |
| Order count | `COUNTD([Order ID])` = 25,728 vs a field also captioned "ORDERS COUNT" built as `{FIXED [Customer ID]:COUNTD([Order ID])}`, which sums to 100,886. | 292% |

Readings built on other datasets are left out of the queue. Nothing is retired here because public workbooks have no usage data.

## Result 2: synthetic estate with usage

Six invented workbooks with planted conflicts and 90 day view counts, to show the full flow including retirement:

| Concept | Readings | Gap | Views exposed |
|---|---|---|---|
| Active customers | 30 day vs 90 day window | 118% | 1,890 |
| Revenue | net of discount, excluding returns, gross | 19% | 2,395 |
| Margin | average of ratios vs ratio of sums | 1.7% | 1,050 |

Order count is agreed and seeded straight to context. Two of six dashboards are retired. Margin ranks last: a real conflict, too small to spend an owner's time on first.

## What broke on real workbooks, and what I changed

The first version was built on the synthetic estate. Real workbooks broke it in useful ways:

* **45 parameters looked like calculated fields.** Tableau stores parameters as calculated columns. They are inputs, so they are now skipped.
* **Most fields are not metrics.** Of 176 real calculated fields, 75 are helpers: labels, tooltips, bins, constants, parameter switches. They are now classified out before grouping.
* **Formulas point at internal ids** like `[Calculation_1248782441598977]`. They are now resolved to captions and inlined, and a real circular reference (Cycle A and Cycle B) is caught instead of crashing.
* **The formula is not the whole definition.** Tableau sets the aggregation on the sheet. The census now reads it from each sheet, which is how the days to ship conflict surfaced.
* **Captions are messy.** "proofit%" is a real caption; close misspellings of core words now match. Identical formulas join a group even when the caption does not.
* **Rules alone place about a quarter of real metrics** (26 of 101). The other 75 include 18 captions in Thai and Portuguese. On a real estate the LLM fallback is required, not optional. Its request and parsing are tested; its accuracy is not yet measured.
* **Some logic is not priced yet:** nested IF, INCLUDE and EXCLUDE level of detail, table calculations, R scripts. Each is reported with the reason instead of failing silently.

## Run it

```bash
pip install -r requirements.txt

# synthetic estate
python sample_estate/make_estate.py
python -m census.run --workbooks sample_estate/workbooks --usage sample_estate/usage_90d.csv \
  --data sample_estate/orders.csv --out out/sample

# public corpus (fetched at pinned commits, not copied into this repo)
python public_corpus/fetch_corpus.py
python -m census.run --workbooks public_corpus/workbooks --data public_corpus/global_superstore_2016.xlsx \
  --team-from-prefix --same-data --out out/public

pytest -q
```

Set `ANTHROPIC_API_KEY` to turn on the LLM fallback for captions the rules cannot place.

Each run writes `census_report.html`, `context.yaml` (agreed definitions plus candidates needing a decision) and `decision_queue.csv`.

## Honest limits

* The public workbooks come from separate authors, not one company, and three source repos are test fixtures for Tableau tools. They stand in for teams inside one estate.
* Exposure on the public corpus counts sheets using a field, because no view data exists.
* Team ownership comes from a workbook preference (synthetic) or the GitHub author (public). A real estate would take it from Tableau Server project and owner metadata.
* Power BI and Looker are next. Their measures (DAX, LookML) are text too, so the same pipeline applies.
