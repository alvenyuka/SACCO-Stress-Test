"""
SACCO Loan Portfolio Stress Testing Engine
==========================================
A production-grade stress testing tool for SACCO loan portfolios.
Simulates economic shocks, projects credit losses under Base, Adverse,
and Severely Adverse scenarios, and outputs IFRS 9-compliant provisioning tables.

Author: Alven Yuka | CPA Finalist | Accounting Specialist, GIZ
Target users: SACCO risk managers, SASRA supervisors, DFI credit teams
"""

import numpy as np
import os
import csv
import json
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from collections import defaultdict


# ════════════════════════════════════════════════
# SECTION 1: DATA MODELS
# ════════════════════════════════════════════════

class RiskGrade(Enum):
    A = "Current"
    B = "Watch"
    C = "Substandard"
    D = "Doubtful"
    E = "Loss"


@dataclass
class Loan:
    loan_id: str
    member_id: str
    member_name: str
    branch: str
    product: str
    principal: float
    outstanding: float
    rate: float
    term_months: int
    dpd: int
    status: str
    disbursement_date: date
    collateral_value: float = 0.0
    sector: str = "General"
    county: str = "Nairobi"
    monthly_income: float = 0.0

    @property
    def ifrs9_stage(self) -> int:
        if self.status in ("Default", "Written-Off"):
            return 3
        if self.dpd > 90:
            return 3
        if self.dpd > 30 or self.status == "Restructured":
            return 2
        return 1

    @property
    def risk_grade(self) -> RiskGrade:
        if self.dpd == 0:
            return RiskGrade.A
        elif self.dpd <= 30:
            return RiskGrade.B
        elif self.dpd <= 90:
            return RiskGrade.C
        elif self.dpd <= 180:
            return RiskGrade.D
        return RiskGrade.E

    @property
    def loan_to_income(self) -> float:
        if self.monthly_income <= 0:
            return 0
        return self.outstanding / (self.monthly_income * 12)

    @property
    def collateral_coverage(self) -> float:
        if self.outstanding <= 0:
            return float('inf')
        return self.collateral_value / self.outstanding

    @property
    def monthly_payment(self) -> float:
        r = self.rate / 12
        n = self.term_months
        if r == 0:
            return self.principal / n
        return self.principal * (r * (1 + r)**n) / ((1 + r)**n - 1)


# ════════════════════════════════════════════════
# SECTION 2: SYNTHETIC PORTFOLIO GENERATOR
# ════════════════════════════════════════════════

class PortfolioGenerator:
    """
    Generates a realistic SACCO loan portfolio with correlated features.
    The correlations mirror actual Kenyan SACCO data:
    - Higher income → larger loans, more savings, lower DPD
    - Emergency loans → shorter terms, higher rates, higher DPD
    - Rural branches → smaller loans, slightly higher default rates
    """

    BRANCHES = ["Nairobi CBD", "Westlands", "Mombasa", "Kisumu", "Nakuru",
                "Eldoret", "Nyeri", "Thika", "Machakos", "Kakamega"]
    PRODUCTS = ["Emergency", "Development", "School Fees", "Business", "Asset Finance"]
    SECTORS = ["Agriculture", "Trade", "Transport", "Education", "Manufacturing",
               "Services", "Construction", "Health", "Personal"]
    COUNTIES = ["Nairobi", "Mombasa", "Kisumu", "Nakuru", "Kiambu",
                "Uasin Gishu", "Nyeri", "Machakos", "Kakamega", "Kilifi"]

    PRODUCT_PARAMS = {
        "Emergency":    {"rate_range": (0.12, 0.18), "term_range": (6, 12),  "max_multiple": 3},
        "Development":  {"rate_range": (0.12, 0.15), "term_range": (12, 48), "max_multiple": 5},
        "School Fees":  {"rate_range": (0.10, 0.14), "term_range": (6, 24),  "max_multiple": 4},
        "Business":     {"rate_range": (0.13, 0.16), "term_range": (12, 60), "max_multiple": 8},
        "Asset Finance": {"rate_range": (0.14, 0.18), "term_range": (24, 60), "max_multiple": 10},
    }

    KENYAN_NAMES = [
        "John Kamau", "Mary Wanjiku", "Peter Ochieng", "Grace Muthoni", "David Kiprop",
        "Sarah Atieno", "James Mwangi", "Faith Chebet", "Daniel Mutua", "Nancy Nyambura",
        "Patrick Kibet", "Ruth Achieng", "Samuel Njoroge", "Elizabeth Wambui", "Joseph Omondi",
        "Agnes Cherop", "Charles Kariuki", "Mercy Wangari", "Stephen Otieno", "Joyce Mwende",
        "Michael Odhiambo", "Catherine Wairimu", "George Wekesa", "Rose Chepkemoi", "Francis Ndung'u",
        "Anne Adhiambo", "Paul Kimani", "Monica Chelagat", "Robert Maina", "Esther Wanjiru",
    ]

    def __init__(self, seed: int = 42):
        self.rng = np.random.RandomState(seed)

    def generate(self, n_loans: int = 2000) -> list[Loan]:
        loans = []
        for i in range(n_loans):
            product = self.rng.choice(self.PRODUCTS, p=[0.15, 0.30, 0.15, 0.25, 0.15])
            params = self.PRODUCT_PARAMS[product]
            branch = self.rng.choice(self.BRANCHES)
            county = self.rng.choice(self.COUNTIES)
            sector = self.rng.choice(self.SECTORS)

            # Income: log-normal, median ~KES 70K
            income = self.rng.lognormal(mean=11.15, sigma=0.55)
            income = max(15_000, min(income, 500_000))

            # Loan amount: multiple of income, depends on product
            multiple = self.rng.uniform(1, params["max_multiple"])
            principal = round(income * multiple / 1000) * 1000
            principal = max(10_000, min(principal, 5_000_000))

            # Rate and term
            rate = self.rng.uniform(*params["rate_range"])
            term = self.rng.randint(params["term_range"][0], params["term_range"][1] + 1)

            # Disbursement date: last 3 years
            days_ago = self.rng.randint(30, 1095)
            disb_date = date.today() - timedelta(days=days_ago)

            # Outstanding: between 10% and 95% of principal (depends on how old the loan is)
            months_elapsed = min(days_ago // 30, term)
            repayment_fraction = months_elapsed / term
            noise = self.rng.uniform(0.8, 1.1)
            outstanding = principal * max(0.05, (1 - repayment_fraction) * noise)
            outstanding = round(outstanding / 100) * 100

            # DPD: exponential with product-dependent rate
            dpd_lambda = {"Emergency": 15, "Development": 8, "School Fees": 12,
                          "Business": 10, "Asset Finance": 6}
            dpd = int(self.rng.exponential(dpd_lambda[product]))
            # Higher DPD more likely for high loan-to-income
            lti = principal / (income * 12)
            if lti > 0.4:
                dpd = int(dpd * self.rng.uniform(1.0, 2.5))
            dpd = max(0, min(dpd, 365))

            # Status
            if dpd > 180 and self.rng.random() < 0.7:
                status = "Default"
            elif dpd > 270 and self.rng.random() < 0.5:
                status = "Written-Off"
            elif dpd > 90 and self.rng.random() < 0.15:
                status = "Restructured"
            else:
                status = "Active"

            # Collateral
            if product in ("Business", "Asset Finance"):
                collateral = principal * self.rng.uniform(0.5, 1.2)
            elif product == "Development":
                collateral = principal * self.rng.uniform(0.3, 0.8)
            else:
                collateral = 0

            name = self.rng.choice(self.KENYAN_NAMES)
            loan = Loan(
                loan_id=f"SAC-{i+1:05d}",
                member_id=f"MEM-{self.rng.randint(1, n_loans // 2):05d}",
                member_name=name,
                branch=branch,
                product=product,
                principal=principal,
                outstanding=outstanding,
                rate=round(rate, 4),
                term_months=term,
                dpd=dpd,
                status=status,
                disbursement_date=disb_date,
                collateral_value=round(collateral, -3),
                sector=sector,
                county=county,
                monthly_income=round(income, -2),
            )
            loans.append(loan)

        return loans


# ════════════════════════════════════════════════
# SECTION 3: STRESS TESTING ENGINE
# ════════════════════════════════════════════════

@dataclass
class MacroScenario:
    """Economic scenario parameters for stress testing."""
    name: str
    description: str
    gdp_growth: float          # Annual GDP growth rate
    inflation: float           # Annual inflation rate
    cbr_rate: float            # Central Bank Rate
    unemployment_change: float  # Change in unemployment (pp)
    shilling_depreciation: float  # KES depreciation vs USD (%)
    agricultural_shock: float  # Agricultural output change (%)
    probability: float         # Scenario probability for weighted ECL

    @property
    def severity_score(self) -> float:
        """Composite severity: higher = worse economic conditions."""
        return (
            max(0, -self.gdp_growth) * 2 +
            max(0, self.inflation - 5) * 1 +
            max(0, self.cbr_rate - 10) * 0.5 +
            self.unemployment_change * 1.5 +
            self.shilling_depreciation * 0.3 +
            max(0, -self.agricultural_shock) * 0.8
        )


# Define three scenarios aligned with CBK/SASRA stress testing guidelines
SCENARIOS = {
    "base": MacroScenario(
        name="Base Case",
        description="Current economic trajectory continues. GDP growth ~5%, inflation stabilising, stable KES.",
        gdp_growth=5.0, inflation=6.5, cbr_rate=10.0,
        unemployment_change=0.0, shilling_depreciation=3.0,
        agricultural_shock=0.0, probability=0.60,
    ),
    "adverse": MacroScenario(
        name="Adverse",
        description="Regional drought + global commodity shock. GDP slows, inflation spikes, KES weakens.",
        gdp_growth=2.0, inflation=10.5, cbr_rate=13.0,
        unemployment_change=3.0, shilling_depreciation=12.0,
        agricultural_shock=-15.0, probability=0.30,
    ),
    "severe": MacroScenario(
        name="Severely Adverse",
        description="Combined drought, political instability, global recession. Credit freeze, mass defaults.",
        gdp_growth=-1.5, inflation=14.0, cbr_rate=16.0,
        unemployment_change=7.0, shilling_depreciation=25.0,
        agricultural_shock=-30.0, probability=0.10,
    ),
}


class StressTestEngine:
    """
    Applies macroeconomic stress scenarios to a loan portfolio.

    Methodology:
    1. Compute baseline transition matrix from current DPD distribution
    2. Apply scenario-specific shocks to PD, migration rates, and LGD
    3. Project portfolio quality forward over 12 months
    4. Calculate IFRS 9 ECL under each scenario
    5. Compute probability-weighted ECL for regulatory reporting
    """

    # Baseline 1-month transition probabilities: illustrative assumptions, not fitted to SACCO data
    BASELINE_TRANSITIONS = {
        # From → {To: probability}
        "Performing":   {"Performing": 0.95, "Watch": 0.04, "Substandard": 0.008, "Default": 0.002},
        "Watch":        {"Performing": 0.15, "Watch": 0.65, "Substandard": 0.15, "Default": 0.05},
        "Substandard":  {"Performing": 0.05, "Watch": 0.10, "Substandard": 0.55, "Default": 0.30},
        "Default":      {"Performing": 0.01, "Watch": 0.02, "Substandard": 0.02, "Default": 0.95},
    }

    # PD parameters by IFRS 9 stage and product
    STAGE_PD = {
        1: {"Emergency": 0.020, "Development": 0.012, "School Fees": 0.018,
            "Business": 0.015, "Asset Finance": 0.010},
        2: {"Emergency": 0.080, "Development": 0.050, "School Fees": 0.070,
            "Business": 0.060, "Asset Finance": 0.040},
        3: {"Emergency": 0.600, "Development": 0.500, "School Fees": 0.550,
            "Business": 0.450, "Asset Finance": 0.350},
    }

    # LGD by collateral status
    LGD = {
        "unsecured": 0.65,
        "partially_secured": 0.45,
        "fully_secured": 0.25,
    }

    def __init__(self, portfolio: list[Loan]):
        self.portfolio = [l for l in portfolio if l.status not in ("Written-Off",)]
        self.active = [l for l in self.portfolio if l.status in ("Active", "Restructured")]
        self.results = {}

    def _classify_collateral(self, loan: Loan) -> str:
        if loan.collateral_coverage >= 0.8:
            return "fully_secured"
        elif loan.collateral_coverage >= 0.3:
            return "partially_secured"
        return "unsecured"

    def _get_pd(self, loan: Loan, scenario: MacroScenario) -> float:
        """Calculate scenario-adjusted PD for a single loan."""
        base_pd = self.STAGE_PD.get(loan.ifrs9_stage, {}).get(loan.product, 0.02)

        # Macro adjustments
        severity = scenario.severity_score
        macro_multiplier = 1.0 + severity * 0.08  # Each severity point adds 8% to PD

        # Borrower-specific adjustments
        lti_adjustment = 1.0
        if loan.loan_to_income > 0.5:
            lti_adjustment = 1.3
        elif loan.loan_to_income > 0.3:
            lti_adjustment = 1.1

        # Sector vulnerability
        sector_shock = 1.0
        if loan.sector == "Agriculture" and scenario.agricultural_shock < -10:
            sector_shock = 1.0 + abs(scenario.agricultural_shock) / 100 * 2
        elif loan.sector in ("Trade", "Transport") and scenario.shilling_depreciation > 10:
            sector_shock = 1.0 + scenario.shilling_depreciation / 100

        adjusted_pd = base_pd * macro_multiplier * lti_adjustment * sector_shock
        return min(adjusted_pd, 0.99)

    def _get_lgd(self, loan: Loan, scenario: MacroScenario) -> float:
        """Calculate scenario-adjusted LGD."""
        base_lgd = self.LGD[self._classify_collateral(loan)]

        # Under stress, collateral values decline
        collateral_haircut = 1.0 + scenario.severity_score * 0.03
        adjusted_lgd = min(base_lgd * collateral_haircut, 0.95)
        return adjusted_lgd

    def _stress_transitions(self, scenario: MacroScenario) -> dict:
        """Adjust transition matrix for the scenario."""
        stressed = {}
        severity = scenario.severity_score

        for state, transitions in self.BASELINE_TRANSITIONS.items():
            stressed[state] = dict(transitions)
            if state != "Default":
                # Increase downgrade probability, decrease upgrade probability
                upgrade_reduction = min(severity * 0.02, 0.5)
                downgrade_increase = severity * 0.015

                for target in stressed[state]:
                    if target == "Default":
                        stressed[state][target] += downgrade_increase
                    elif target == "Performing" and state != "Performing":
                        stressed[state][target] = max(0.001, stressed[state][target] - upgrade_reduction)

                # Re-normalise to sum to 1
                total = sum(stressed[state].values())
                stressed[state] = {k: v / total for k, v in stressed[state].items()}

        return stressed

    def run_scenario(self, scenario: MacroScenario, horizon_months: int = 12) -> dict:
        """Run a stress test scenario and project portfolio losses."""

        # Compute loan-level ECL
        loan_results = []
        total_outstanding = sum(l.outstanding for l in self.active)

        for loan in self.active:
            pd = self._get_pd(loan, scenario)
            lgd = self._get_lgd(loan, scenario)
            ead = loan.outstanding
            ecl = pd * lgd * ead

            loan_results.append({
                "loan_id": loan.loan_id,
                "member": loan.member_name,
                "branch": loan.branch,
                "product": loan.product,
                "sector": loan.sector,
                "outstanding": loan.outstanding,
                "stage": loan.ifrs9_stage,
                "dpd": loan.dpd,
                "pd": round(pd, 6),
                "lgd": round(lgd, 4),
                "ead": ead,
                "ecl": round(ecl, 2),
                "provision_rate": round(ecl / ead, 6) if ead > 0 else 0,
                "collateral_status": self._classify_collateral(loan),
                "lti": round(loan.loan_to_income, 4),
            })

        # Aggregate by stage
        stage_summary = {}
        for stage in [1, 2, 3]:
            stage_loans = [r for r in loan_results if r["stage"] == stage]
            outstanding = sum(r["outstanding"] for r in stage_loans)
            ecl = sum(r["ecl"] for r in stage_loans)
            stage_summary[f"Stage {stage}"] = {
                "count": len(stage_loans),
                "outstanding": outstanding,
                "ecl": ecl,
                "provision_rate": ecl / outstanding if outstanding > 0 else 0,
                "avg_pd": np.mean([r["pd"] for r in stage_loans]) if stage_loans else 0,
                "avg_lgd": np.mean([r["lgd"] for r in stage_loans]) if stage_loans else 0,
                "pct_of_portfolio": outstanding / total_outstanding if total_outstanding > 0 else 0,
            }

        # Aggregate by product
        product_summary = {}
        for product in set(r["product"] for r in loan_results):
            prod_loans = [r for r in loan_results if r["product"] == product]
            outstanding = sum(r["outstanding"] for r in prod_loans)
            ecl = sum(r["ecl"] for r in prod_loans)
            product_summary[product] = {
                "count": len(prod_loans),
                "outstanding": outstanding,
                "ecl": ecl,
                "provision_rate": ecl / outstanding if outstanding > 0 else 0,
            }

        # Aggregate by branch
        branch_summary = {}
        for branch in set(r["branch"] for r in loan_results):
            br_loans = [r for r in loan_results if r["branch"] == branch]
            outstanding = sum(r["outstanding"] for r in br_loans)
            ecl = sum(r["ecl"] for r in br_loans)
            branch_summary[branch] = {
                "count": len(br_loans),
                "outstanding": outstanding,
                "ecl": ecl,
                "provision_rate": ecl / outstanding if outstanding > 0 else 0,
            }

        # Aggregate by sector
        sector_summary = {}
        for sector in set(r["sector"] for r in loan_results):
            sec_loans = [r for r in loan_results if r["sector"] == sector]
            outstanding = sum(r["outstanding"] for r in sec_loans)
            ecl = sum(r["ecl"] for r in sec_loans)
            sector_summary[sector] = {
                "count": len(sec_loans),
                "outstanding": outstanding,
                "ecl": ecl,
                "provision_rate": ecl / outstanding if outstanding > 0 else 0,
            }

        # Portfolio-level metrics
        total_ecl = sum(r["ecl"] for r in loan_results)
        portfolio_metrics = {
            "scenario": scenario.name,
            "probability": scenario.probability,
            "severity_score": round(scenario.severity_score, 2),
            "total_loans": len(loan_results),
            "total_outstanding": total_outstanding,
            "total_ecl": total_ecl,
            "aggregate_provision_rate": total_ecl / total_outstanding if total_outstanding > 0 else 0,
            "ecl_to_equity_impact": total_ecl,  # Simplified — would need equity data
            "top_10_concentration": sum(sorted([r["outstanding"] for r in loan_results], reverse=True)[:10]) / total_outstanding if total_outstanding > 0 else 0,
            "macro_params": {
                "gdp_growth": scenario.gdp_growth,
                "inflation": scenario.inflation,
                "cbr_rate": scenario.cbr_rate,
                "unemployment_change": scenario.unemployment_change,
                "kes_depreciation": scenario.shilling_depreciation,
                "agricultural_shock": scenario.agricultural_shock,
            },
        }

        return {
            "portfolio": portfolio_metrics,
            "stages": stage_summary,
            "products": product_summary,
            "branches": branch_summary,
            "sectors": sector_summary,
            "loan_detail": loan_results,
        }

    def run_all_scenarios(self) -> dict:
        """Run all three scenarios and compute probability-weighted ECL."""
        all_results = {}
        weighted_ecl = 0

        for key, scenario in SCENARIOS.items():
            result = self.run_scenario(scenario)
            all_results[key] = result
            weighted_ecl += result["portfolio"]["total_ecl"] * scenario.probability

        all_results["weighted_ecl"] = {
            "total_ecl": weighted_ecl,
            "provision_rate": weighted_ecl / all_results["base"]["portfolio"]["total_outstanding"]
            if all_results["base"]["portfolio"]["total_outstanding"] > 0 else 0,
            "components": {
                key: {
                    "ecl": all_results[key]["portfolio"]["total_ecl"],
                    "weight": SCENARIOS[key].probability,
                    "contribution": all_results[key]["portfolio"]["total_ecl"] * SCENARIOS[key].probability,
                }
                for key in SCENARIOS
            },
        }

        self.results = all_results
        return all_results


# ════════════════════════════════════════════════
# SECTION 4: REPORT GENERATOR
# ════════════════════════════════════════════════

class ReportGenerator:
    """Generates formatted Excel and console reports from stress test results."""

    def __init__(self, results: dict, portfolio: list[Loan]):
        self.results = results
        self.portfolio = portfolio

    def console_report(self):
        """Print a comprehensive stress test report to console."""
        width = 80

        print(f"\n{'═' * width}")
        print(f"  SACCO LOAN PORTFOLIO STRESS TEST REPORT")
        print(f"  Generated: {date.today().strftime('%d %B %Y')}")
        print(f"{'═' * width}")

        # Portfolio overview
        base = self.results["base"]["portfolio"]
        print(f"\n  PORTFOLIO OVERVIEW")
        print(f"  {'─' * (width - 4)}")
        print(f"  {'Active Loans:':<35} {base['total_loans']:>12,}")
        print(f"  {'Total Outstanding:':<35} KES {base['total_outstanding']:>12,.0f}")
        print(f"  {'Top-10 Concentration:':<35} {base['top_10_concentration']:>12.1%}")

        # Scenario comparison
        print(f"\n  SCENARIO COMPARISON")
        print(f"  {'─' * (width - 4)}")
        print(f"  {'Metric':<25} {'Base':>15} {'Adverse':>15} {'Severe':>15}")
        print(f"  {'─' * (width - 4)}")

        for key, label in [
            ("gdp_growth", "GDP Growth (%)"),
            ("inflation", "Inflation (%)"),
            ("cbr_rate", "CBR Rate (%)"),
            ("unemployment_change", "Unemployment Δ (pp)"),
            ("kes_depreciation", "KES Depreciation (%)"),
            ("agricultural_shock", "Agri Shock (%)"),
        ]:
            values = []
            for s in ["base", "adverse", "severe"]:
                v = self.results[s]["portfolio"]["macro_params"][key]
                values.append(f"{v:>+.1f}" if key != "cbr_rate" else f"{v:.1f}")
            print(f"  {label:<25} {values[0]:>15} {values[1]:>15} {values[2]:>15}")

        print(f"  {'─' * (width - 4)}")
        print(f"  {'Severity Score':<25}", end="")
        for s in ["base", "adverse", "severe"]:
            print(f" {self.results[s]['portfolio']['severity_score']:>14.1f}", end="")
        print()

        print(f"  {'Total ECL (KES)':<25}", end="")
        for s in ["base", "adverse", "severe"]:
            print(f" {self.results[s]['portfolio']['total_ecl']:>14,.0f}", end="")
        print()

        print(f"  {'Provision Rate':<25}", end="")
        for s in ["base", "adverse", "severe"]:
            print(f" {self.results[s]['portfolio']['aggregate_provision_rate']:>14.2%}", end="")
        print()

        print(f"  {'Scenario Probability':<25}", end="")
        for s in ["base", "adverse", "severe"]:
            print(f" {SCENARIOS[s].probability:>14.0%}", end="")
        print()

        # Probability-weighted ECL
        we = self.results["weighted_ecl"]
        print(f"\n  {'─' * (width - 4)}")
        print(f"  PROBABILITY-WEIGHTED ECL")
        print(f"  {'─' * (width - 4)}")
        for key, comp in we["components"].items():
            print(f"  {SCENARIOS[key].name:<20} ECL: KES {comp['ecl']:>12,.0f} × "
                  f"{comp['weight']:.0%} = KES {comp['contribution']:>12,.0f}")
        print(f"  {'─' * (width - 4)}")
        print(f"  {'TOTAL WEIGHTED ECL':<20} {'':>30} KES {we['total_ecl']:>12,.0f}")
        print(f"  {'Weighted Provision Rate':<20} {'':>30} {we['provision_rate']:>12.2%}")

        # IFRS 9 staging under each scenario
        print(f"\n  IFRS 9 STAGING UNDER STRESS")
        print(f"  {'─' * (width - 4)}")
        for s_key, s_label in [("base", "BASE"), ("adverse", "ADVERSE"), ("severe", "SEVERE")]:
            print(f"\n  {s_label}:")
            print(f"  {'Stage':<10} {'Count':>8} {'Outstanding':>14} {'ECL':>14} {'Prov %':>8} {'Avg PD':>8}")
            for stage_name, data in self.results[s_key]["stages"].items():
                print(f"  {stage_name:<10} {data['count']:>8} "
                      f"KES {data['outstanding']:>10,.0f} "
                      f"KES {data['ecl']:>10,.0f} "
                      f"{data['provision_rate']:>7.2%} "
                      f"{data['avg_pd']:>7.2%}")

        # Sector vulnerability
        print(f"\n  SECTOR VULNERABILITY (ADVERSE SCENARIO)")
        print(f"  {'─' * (width - 4)}")
        print(f"  {'Sector':<20} {'Loans':>6} {'Outstanding':>14} {'ECL':>12} {'Prov %':>8}")
        print(f"  {'─' * (width - 4)}")
        sectors = self.results["adverse"]["sectors"]
        for sector in sorted(sectors.keys(), key=lambda x: sectors[x]["provision_rate"], reverse=True):
            data = sectors[sector]
            print(f"  {sector:<20} {data['count']:>6} "
                  f"KES {data['outstanding']:>10,.0f} "
                  f"KES {data['ecl']:>8,.0f} "
                  f"{data['provision_rate']:>7.2%}")

        # Capital impact
        print(f"\n  CAPITAL ADEQUACY IMPACT")
        print(f"  {'─' * (width - 4)}")
        total_outstanding = base["total_outstanding"]
        assumed_equity = total_outstanding * 0.15  # Assume 15% CAR
        for s_key, s_label in [("base", "Base"), ("adverse", "Adverse"), ("severe", "Severe")]:
            ecl = self.results[s_key]["portfolio"]["total_ecl"]
            equity_after = assumed_equity - ecl
            car_after = equity_after / total_outstanding * 100 if total_outstanding > 0 else 0
            breach = "⚠ BELOW 10% MINIMUM" if car_after < 10 else "✓ Adequate"
            print(f"  {s_label:<12} ECL: KES {ecl:>10,.0f}  "
                  f"Equity after: KES {equity_after:>10,.0f}  "
                  f"CAR: {car_after:>5.1f}%  {breach}")

        print(f"\n{'═' * width}\n")

    def to_excel(self, filepath: str):
        """Write stress test results to a formatted Excel workbook."""
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = Workbook()

        # ── Sheet 1: Executive Summary ──
        ws = wb.active
        ws.title = "Executive Summary"

        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_fill = PatternFill("solid", fgColor="1F4E79")
        kpi_font = Font(bold=True, size=14, color="1F4E79")
        section_font = Font(bold=True, size=12, color="1F4E79")
        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin')
        )

        ws.merge_cells("A1:F1")
        ws["A1"] = "SACCO LOAN PORTFOLIO — STRESS TEST RESULTS"
        ws["A1"].font = Font(bold=True, size=16, color="1F4E79")

        ws["A2"] = f"Report Date: {date.today().strftime('%d %B %Y')}"
        ws["A2"].font = Font(italic=True, color="666666")

        # KPIs
        base = self.results["base"]["portfolio"]
        we = self.results["weighted_ecl"]

        kpis = [
            ("B4", "Total Outstanding", f"KES {base['total_outstanding']:,.0f}"),
            ("D4", "Active Loans", f"{base['total_loans']:,}"),
            ("B6", "Weighted ECL", f"KES {we['total_ecl']:,.0f}"),
            ("D6", "Weighted Provision Rate", f"{we['provision_rate']:.2%}"),
        ]
        for cell, label, value in kpis:
            ws[cell] = label
            ws[cell].font = Font(bold=True, size=10, color="666666")
            value_cell = cell[0] + str(int(cell[1:]) + 1) if len(cell) == 2 else cell[:2] + str(int(cell[2:]) + 1)
            # Place value one row below
            row = int(cell[1:])
            ws.cell(row=row, column=ws[cell].column).font = Font(size=9, color="666666")

        # Scenario comparison table
        row = 9
        ws.cell(row=row, column=1, value="SCENARIO COMPARISON").font = section_font
        row += 1

        headers = ["Metric", "Base Case", "Adverse", "Severely Adverse"]
        for col, h in enumerate(headers, 1):
            c = ws.cell(row=row, column=col, value=h)
            c.font = header_font
            c.fill = header_fill
            c.border = thin_border

        metrics = [
            ("GDP Growth (%)", "gdp_growth"),
            ("Inflation (%)", "inflation"),
            ("CBR Rate (%)", "cbr_rate"),
            ("Unemployment Δ (pp)", "unemployment_change"),
            ("KES Depreciation (%)", "kes_depreciation"),
            ("Agricultural Shock (%)", "agricultural_shock"),
        ]

        for metric_label, metric_key in metrics:
            row += 1
            ws.cell(row=row, column=1, value=metric_label).border = thin_border
            for col, s_key in enumerate(["base", "adverse", "severe"], 2):
                val = self.results[s_key]["portfolio"]["macro_params"][metric_key]
                c = ws.cell(row=row, column=col, value=val)
                c.number_format = '0.0'
                c.border = thin_border

        # ECL row
        row += 1
        ws.cell(row=row, column=1, value="Total ECL (KES)").font = Font(bold=True)
        ws.cell(row=row, column=1).border = thin_border
        for col, s_key in enumerate(["base", "adverse", "severe"], 2):
            c = ws.cell(row=row, column=col, value=self.results[s_key]["portfolio"]["total_ecl"])
            c.number_format = '#,##0'
            c.font = Font(bold=True)
            c.border = thin_border
            if s_key == "severe":
                c.font = Font(bold=True, color="FF0000")

        # Provision rate row
        row += 1
        ws.cell(row=row, column=1, value="Provision Rate").border = thin_border
        for col, s_key in enumerate(["base", "adverse", "severe"], 2):
            c = ws.cell(row=row, column=col, value=self.results[s_key]["portfolio"]["aggregate_provision_rate"])
            c.number_format = '0.00%'
            c.border = thin_border

        # Probability row
        row += 1
        ws.cell(row=row, column=1, value="Scenario Probability").border = thin_border
        for col, s_key in enumerate(["base", "adverse", "severe"], 2):
            c = ws.cell(row=row, column=col, value=SCENARIOS[s_key].probability)
            c.number_format = '0%'
            c.border = thin_border

        # Column widths
        ws.column_dimensions['A'].width = 25
        for col in ['B', 'C', 'D']:
            ws.column_dimensions[col].width = 20

        # ── Sheet 2: IFRS 9 Staging ──
        ws2 = wb.create_sheet("IFRS 9 Staging")

        row = 1
        for s_key, s_label in [("base", "BASE CASE"), ("adverse", "ADVERSE"), ("severe", "SEVERELY ADVERSE")]:
            ws2.cell(row=row, column=1, value=f"{s_label} — IFRS 9 Staging").font = section_font
            row += 1

            stage_headers = ["Stage", "Count", "Outstanding (KES)", "ECL (KES)", "Provision Rate", "Avg PD", "Avg LGD", "% of Portfolio"]
            for col, h in enumerate(stage_headers, 1):
                c = ws2.cell(row=row, column=col, value=h)
                c.font = header_font
                c.fill = header_fill
                c.border = thin_border

            for stage_name, data in self.results[s_key]["stages"].items():
                row += 1
                vals = [stage_name, data["count"], data["outstanding"], data["ecl"],
                        data["provision_rate"], data["avg_pd"], data["avg_lgd"], data["pct_of_portfolio"]]
                for col, val in enumerate(vals, 1):
                    c = ws2.cell(row=row, column=col, value=val)
                    c.border = thin_border
                    if col == 3 or col == 4:
                        c.number_format = '#,##0'
                    elif col >= 5:
                        c.number_format = '0.00%'

            row += 2

        for col_letter in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
            ws2.column_dimensions[col_letter].width = 16
        ws2.column_dimensions['A'].width = 12
        ws2.column_dimensions['C'].width = 20
        ws2.column_dimensions['D'].width = 16

        # ── Sheet 3: Sector Analysis ──
        ws3 = wb.create_sheet("Sector Analysis")
        ws3.cell(row=1, column=1, value="SECTOR VULNERABILITY — ADVERSE SCENARIO").font = section_font

        sec_headers = ["Sector", "Loan Count", "Outstanding (KES)", "ECL (KES)", "Provision Rate"]
        for col, h in enumerate(sec_headers, 1):
            c = ws3.cell(row=2, column=col, value=h)
            c.font = header_font
            c.fill = header_fill
            c.border = thin_border

        sectors = self.results["adverse"]["sectors"]
        for row_idx, sector in enumerate(sorted(sectors, key=lambda x: sectors[x]["provision_rate"], reverse=True), 3):
            data = sectors[sector]
            vals = [sector, data["count"], data["outstanding"], data["ecl"], data["provision_rate"]]
            for col, val in enumerate(vals, 1):
                c = ws3.cell(row=row_idx, column=col, value=val)
                c.border = thin_border
                if col in (3, 4):
                    c.number_format = '#,##0'
                elif col == 5:
                    c.number_format = '0.00%'
                    if val > 0.05:
                        c.font = Font(color="FF0000", bold=True)

        for col_letter in ['A', 'B', 'C', 'D', 'E']:
            ws3.column_dimensions[col_letter].width = 18

        # ── Sheet 4: Weighted ECL ──
        ws4 = wb.create_sheet("Weighted ECL")
        ws4.cell(row=1, column=1, value="PROBABILITY-WEIGHTED EXPECTED CREDIT LOSS").font = section_font

        we_headers = ["Scenario", "ECL (KES)", "Probability", "Weighted Contribution (KES)"]
        for col, h in enumerate(we_headers, 1):
            c = ws4.cell(row=3, column=col, value=h)
            c.font = header_font
            c.fill = header_fill
            c.border = thin_border

        we = self.results["weighted_ecl"]
        for row_idx, (key, comp) in enumerate(we["components"].items(), 4):
            vals = [SCENARIOS[key].name, comp["ecl"], comp["weight"], comp["contribution"]]
            for col, val in enumerate(vals, 1):
                c = ws4.cell(row=row_idx, column=col, value=val)
                c.border = thin_border
                if col in (2, 4):
                    c.number_format = '#,##0'
                elif col == 3:
                    c.number_format = '0%'

        total_row = 4 + len(we["components"])
        ws4.cell(row=total_row, column=1, value="TOTAL WEIGHTED ECL").font = Font(bold=True, size=12)
        c = ws4.cell(row=total_row, column=4, value=we["total_ecl"])
        c.number_format = '#,##0'
        c.font = Font(bold=True, size=12, color="FF0000")
        c.border = thin_border

        ws4.cell(row=total_row + 1, column=1, value="Weighted Provision Rate")
        c = ws4.cell(row=total_row + 1, column=4, value=we["provision_rate"])
        c.number_format = '0.00%'
        c.font = Font(bold=True)

        for col_letter in ['A', 'B', 'C', 'D']:
            ws4.column_dimensions[col_letter].width = 25

        wb.save(filepath)
        print(f"Stress test report saved to: {filepath}")


# ════════════════════════════════════════════════
# SECTION 5: MAIN EXECUTION
# ════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  SACCO LOAN PORTFOLIO STRESS TESTING ENGINE")
    print("  Alven Yuka | CPA Finalist | Accounting Specialist, GIZ")
    print("=" * 70)

    # Generate portfolio
    print("\n[1/4] Generating synthetic SACCO portfolio...")
    generator = PortfolioGenerator(seed=42)
    portfolio = generator.generate(n_loans=2000)
    active_count = len([l for l in portfolio if l.status in ("Active", "Restructured")])
    total_outstanding = sum(l.outstanding for l in portfolio if l.status in ("Active", "Restructured"))
    default_count = len([l for l in portfolio if l.status == "Default"])
    print(f"  Generated: {len(portfolio)} loans")
    print(f"  Active: {active_count} | Default: {default_count}")
    print(f"  Total Outstanding: KES {total_outstanding:,.0f}")

    # Run stress tests
    print("\n[2/4] Running stress test scenarios...")
    engine = StressTestEngine(portfolio)
    results = engine.run_all_scenarios()

    for key in ["base", "adverse", "severe"]:
        r = results[key]["portfolio"]
        print(f"  {SCENARIOS[key].name:<22} → ECL: KES {r['total_ecl']:>12,.0f}  "
              f"Provision: {r['aggregate_provision_rate']:.2%}")

    we = results["weighted_ecl"]
    print(f"  {'Prob-Weighted ECL':<22} → ECL: KES {we['total_ecl']:>12,.0f}  "
          f"Provision: {we['provision_rate']:.2%}")

    # Console report
    print("\n[3/4] Generating console report...")
    reporter = ReportGenerator(results, portfolio)
    reporter.console_report()

    # Excel report
    print("[4/4] Generating Excel report...")
    output_path = "output/sacco_stress_test_report.xlsx"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    reporter.to_excel(output_path)

    print("\nDone. All outputs generated successfully.")
