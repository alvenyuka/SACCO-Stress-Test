# SACCO Stress Test

A Python tool that estimates how much a Kenyan savings and credit co-operative could lose on its loans in a downturn, run here on a made-up (synthetic) loan book.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![tests](https://github.com/alvenyuka/SACCO-Stress-Test/actions/workflows/ci.yml/badge.svg)](https://github.com/alvenyuka/SACCO-Stress-Test/actions/workflows/ci.yml)

![Two bar charts. Left: expected credit loss in KES millions for the base, adverse and severely adverse scenarios. Right: capital ratio after those losses, with the 10% minimum marked and the severe scenario below it](figures/ecl_and_capital_by_scenario.png)

## What this project does

A **SACCO** (savings and credit co-operative) lends its members' own savings back to them, so when borrowers stop repaying, the loss comes straight out of members' capital. Under the accounting standard **IFRS 9**, a lender must set aside money today for loans that may go bad. That amount is the **expected credit loss (ECL)**. The board needs to know how large it would be if the economy turned bad, and whether capital would still be enough afterwards.

This project answers that: how much would the expected credit loss rise in a drought-and-inflation shock, and would capital stay above 10% of the loan book?

**Data: the loan book is synthetic.** `PortfolioGenerator` in `stress_test_engine.py` invents 2,000 loans (seed 42, KES 231,864,700 outstanding). No real SACCO or member data is used, so the results show how the model behaves, not the state of any real lender.

## Results

- In the base scenario the expected credit loss is KES 1,813,103. In the severely adverse scenario it is KES 19,270,186, about ten times as much.
- Weighting the three scenarios by how likely each is (60%, 30%, 10%) gives KES 5,439,466. Under IFRS 9 the provision is a probability-weighted figure like this one.
- With equity assumed at 15% of loans, the capital ratio after losses falls from 14.2% (base) to 11.5% (adverse) to 6.7% (severe). The severe case is KES 7,676,951 short of a 10% minimum.

| Scenario | Weight | Severity score | Expected credit loss (KES) | Loss as % of loans | Capital ratio after losses |
|---|---|---|---:|---:|---:|
| Base Case | 60% | 2.4 | 1,813,103 | 0.78% | 14.2% |
| Adverse | 30% | 27.1 | 8,081,952 | 3.49% | 11.5% |
| Severely Adverse | 10% | 57.0 | 19,270,186 | 8.31% | 6.7% (below 10%) |
| Probability-weighted | | | 5,439,466 | 2.35% | |

All figures are in `outputs/results.json`, which `make_figures.py` writes from a fresh run. Assumptions behind the capital ratio: equity equals 15% of outstanding loans before losses, the ratio divides by loans (not risk-weighted assets), and 10% is the minimum tested against.

![Bar chart of the adverse-scenario loss rate by borrower sector. Agriculture is highest at 4.52% of outstanding loans](figures/sector_provision_adverse.png)

*Under the adverse scenario agriculture has the highest loss rate (4.52% of outstanding), because the drought hits farm incomes. Services and manufacturing are lowest, both about 2.94%.*

## How I built it

Each step is a piece of `stress_test_engine.py` unless stated.

1. **Make a loan book.** `PortfolioGenerator` draws 2,000 loans across five products (Emergency, Development, School Fees, Business, Asset Finance), ten branches and nine borrower sectors. Loan size follows the borrower's income, and rates and terms follow the product. The fixed seed means every run produces the same loans.
2. **Put each loan in an IFRS 9 stage.** The three **stages** sort loans by how much trouble they are in: Stage 1 is performing, Stage 2 has had a significant rise in risk (here, more than 30 days past due or restructured), Stage 3 is credit-impaired (more than 90 days past due, or defaulted or written off). Staging is the `Loan.ifrs9_stage` property.
3. **Give each loan a probability of default.** The **probability of default (PD)** is the chance the borrower fails to repay over the period. It starts from a table by stage and product (for example 2.0% for a Stage 1 Emergency loan), then is scaled up for the scenario and for risky borrowers (`_get_pd`, step 5 below), and capped at 99%.
4. **Give each loan a loss given default.** The **loss given default (LGD)** is the share of the balance the lender loses if the borrower does default. It is 65% for an unsecured loan, 45% if collateral covers 30% to 80% of the balance, and 25% if it covers 80% or more (`_get_lgd`). It is then raised by 3% for each severity point, because collateral sells for less in a downturn, capped at 95%.
5. **Define the scenarios.** `MacroScenario` holds six economic inputs: GDP growth, inflation, the central bank rate, change in unemployment, shilling depreciation and an agricultural output shock. The three scenarios (base, adverse, severely adverse) use values I set by hand; they are not taken from a regulator. Each scenario is summarised as one **severity score** (a weighted sum of how far each input is from normal), and that score drives step 3 and step 4. Each severity point raises PD by 8%. Borrowers whose outstanding balance exceeds half a year's income have PD raised by 30% (10% if above 30%). Agricultural loans get a drought uplift when the agricultural shock is worse than -10%, and trade and transport loans get a shilling uplift when depreciation is above 10%.
6. **Multiply it out.** Expected credit loss for a loan is PD x LGD x **EAD**, where exposure at default (EAD) is the outstanding balance (`stress_one_loan`). Totals are added up by stage, product, branch and sector.
7. **Weight the scenarios.** `run_all_scenarios` multiplies each scenario's total by its probability and sums them. Under IFRS 9 the provision should reflect a range of outcomes, not only the central one.
8. **Test capital.** `make_figures.py` takes equity as 15% of the loan book, subtracts each scenario's loss, and divides by the loan book. This is a simplified **capital adequacy ratio**: capital as a share of what the lender has lent. The shortfall is how much extra capital would bring the ratio back to 10%.
9. **Write the outputs.** `stress_test_engine.py` prints a console report and writes a four-sheet Excel workbook to `output/` (Executive Summary, IFRS 9 Staging, Sector Analysis, Weighted ECL). The Executive Summary opens with four headline figures (total outstanding, active loans, weighted ECL, weighted provision rate), each under its label. `make_figures.py` writes `outputs/results.json` and the two charts in `figures/`.
10. **Lock the numbers with tests.** `tests/test_engine.py` re-runs the engine and checks the result against `outputs/results.json`, so the figures above cannot drift from the code.

## Problems I hit

- **The README claimed loans move between stages under stress, and they do not.** An earlier version of the engine had a method that built a stressed migration matrix, but nothing called it; a review on 2026-10-18 found this, and the unused method has since been removed. Stress raises each loan's PD and LGD, but a Stage 1 loan stays Stage 1. The earlier README was wrong; the claim is removed and the gap is listed under Limits.
- **The console report crashes on a Windows console.** It prints box-drawing characters, and the default cp1252 console cannot encode them. The script wrote its outputs and then failed, so the run looked broken. Setting `PYTHONIOENCODING=utf-8` before running fixes it.

## Data

| Source | Terms | Size | Period |
|---|---|---|---|
| Synthetic loans from `PortfolioGenerator` (seed 42) | MIT, this repository | 2,000 loans, KES 231,864,700 outstanding | a single point in time, regenerated on each run |

Branch names are Kenyan towns and member names are generic Kenyan names, used only to make reports readable.

## Limits

- **The loan book is synthetic.** The figures show how the model behaves, not any real lender's position.
- **Loans do not move between stages under stress.** Staging comes from days past due at the reporting date and stays fixed in every scenario. Stress raises PD and LGD but never moves a loan to a worse stage, so the loss in the severe case is probably understated.
- **The inputs are my assumptions.** The stage PDs, LGDs, severity multipliers and scenario values are set by hand. They are not fitted to historical SACCO defaults and not taken from CBK or SASRA scenarios.
- **One PD per loan.** There are no separate 12-month and lifetime PDs and no discounting at the loan's interest rate.
- **The capital test is a sensitivity, not a regulatory return.** Equity is assumed at 15% of loans, and the denominator is loans rather than risk-weighted assets.
- **EAD is the outstanding balance only.** Undrawn commitments and early repayment are not modelled.

## How to run

Needs Python 3. Libraries: numpy, openpyxl and matplotlib (pinned in `requirements.txt`), plus pytest for the tests.

```bash
pip install -r requirements.txt
PYTHONIOENCODING=utf-8 python stress_test_engine.py   # console report, writes output/sacco_stress_test_report.xlsx
python make_figures.py                                 # writes outputs/results.json and the two charts
pip install pytest && python -m pytest                 # 5 tests
```

## Project structure

```
stress_test_engine.py   loan generator, staging, scenarios, PD / LGD / ECL, console and Excel reports
make_figures.py         writes outputs/results.json and the charts in figures/
outputs/results.json    every figure quoted above
output/                 the Excel workbook written by stress_test_engine.py
figures/                the two charts
tests/test_engine.py    5 tests: same seed same result, loss rises with severity, weighted ECL arithmetic,
                        capital arithmetic, committed results match a fresh run
```

## License

MIT. See [`LICENSE`](LICENSE).

Alven Yuka · [LinkedIn](https://www.linkedin.com/in/alven-yuka-610b78174/) · [Email](mailto:alvenyuka2@gmail.com)
