"""
SACCO loan portfolio stress test.

Builds a synthetic SACCO loan book, applies three hand-set macro scenarios (Base, Adverse,
Severely Adverse) to each loan's PD and LGD, and reports expected credit loss (ECL) by IFRS 9 stage,
product, branch and sector. Loans keep their reporting-date stage under stress (no stage migration).

Author: Alven Yuka | CPA Finalist
"""

import numpy as np
import os
from datetime import date, timedelta
from dataclasses import dataclass


# DATA MODELS

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
    def loan_to_income(self) -> float:
        if self.monthly_income <= 0:
            return 0
        return self.outstanding / (self.monthly_income * 12)

    @property
    def collateral_coverage(self) -> float:
        if self.outstanding <= 0:
            return float('inf')
        return self.collateral_value / self.outstanding


# SYNTHETIC PORTFOLIO GENERATOR

class PortfolioGenerator:
    """
    Generates a synthetic SACCO loan portfolio. The data is made up, not real SACCO records.
    Some features are linked on purpose:
    - Higher income gives larger loans
    - Emergency loans have shorter terms, higher rates than Development and School Fees loans, and more days past due
    - Loans that are large relative to income tend to have more days past due
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


# STRESS TESTING ENGINE

# Severity score weights: points added per unit of each macro variable.
# Only the part of a variable on the bad side of its threshold counts.
GDP_WEIGHT = 2.0              # per percentage point of negative GDP growth
INFLATION_THRESHOLD = 5       # inflation above this (%) counts as stress
INFLATION_WEIGHT = 1.0        # per point of inflation above the threshold
CBR_THRESHOLD = 10            # central bank rate above this (%) counts as stress
CBR_WEIGHT = 0.5              # per point of CBR above the threshold
UNEMPLOYMENT_WEIGHT = 1.5     # per point of rise in unemployment
DEPRECIATION_WEIGHT = 0.3     # per % of shilling depreciation
AGRI_WEIGHT = 0.8             # per % fall in agricultural output


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
        """One number for how bad the scenario is: higher = worse."""
        gdp_points = max(0, -self.gdp_growth) * GDP_WEIGHT
        inflation_points = max(0, self.inflation - INFLATION_THRESHOLD) * INFLATION_WEIGHT
        cbr_points = max(0, self.cbr_rate - CBR_THRESHOLD) * CBR_WEIGHT
        unemployment_points = self.unemployment_change * UNEMPLOYMENT_WEIGHT
        depreciation_points = self.shilling_depreciation * DEPRECIATION_WEIGHT
        agri_points = max(0, -self.agricultural_shock) * AGRI_WEIGHT
        return (gdp_points + inflation_points + cbr_points
                + unemployment_points + depreciation_points + agri_points)


# Three hand-set scenarios. The values are my own assumptions, not taken from CBK or SASRA.
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


# PD and LGD adjustment constants (all hand-set assumptions)
DEFAULT_BASE_PD = 0.02        # PD used if a stage/product pair is missing from STAGE_PD
PD_PER_SEVERITY_POINT = 0.08  # each severity point raises PD by 8%
LTI_HIGH = 0.5                # loan-to-income above this is high-risk
LTI_HIGH_MULTIPLIER = 1.3     # PD multiplier for high loan-to-income
LTI_MEDIUM = 0.3              # loan-to-income above this is medium-risk
LTI_MEDIUM_MULTIPLIER = 1.1   # PD multiplier for medium loan-to-income
AGRI_SHOCK_TRIGGER = -10      # agricultural sector is hit when output falls by more than 10%
AGRI_SECTOR_SENSITIVITY = 2   # agriculture borrowers feel the output fall twice over
DEPRECIATION_TRIGGER = 10     # trade and transport are hit when the shilling loses more than 10%
MAX_PD = 0.99                 # cap so PD stays below 100%
LGD_PER_SEVERITY_POINT = 0.03  # collateral loses value under stress: 3% more LGD per severity point
MAX_LGD = 0.95                # cap on stressed LGD


class StressTestEngine:
    """
    Applies the macro scenarios to a loan portfolio.

    Steps for each scenario:
    1. Look up a base PD from the loan's IFRS 9 stage and product.
    2. Scale the PD up for the scenario's severity, the borrower's loan-to-income and the loan's sector.
    3. Look up a base LGD from collateral cover and scale it up for the severity.
    4. ECL per loan = PD x LGD x outstanding balance.
    5. Add up ECL by stage, product, branch and sector, then probability-weight the three scenarios.

    A loan keeps its reporting-date stage in every scenario.
    """

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
        # Only Active and Restructured loans get an ECL; Default and Written-Off loans are left out
        self.active = [l for l in portfolio if l.status in ("Active", "Restructured")]
        self.results = {}

    def _classify_collateral(self, loan: Loan) -> str:
        if loan.collateral_coverage >= 0.8:
            return "fully_secured"
        elif loan.collateral_coverage >= 0.3:
            return "partially_secured"
        return "unsecured"

    def _lti_multiplier(self, loan: Loan) -> float:
        if loan.loan_to_income > LTI_HIGH:
            return LTI_HIGH_MULTIPLIER
        if loan.loan_to_income > LTI_MEDIUM:
            return LTI_MEDIUM_MULTIPLIER
        return 1.0

    def _sector_multiplier(self, loan: Loan, scenario: MacroScenario) -> float:
        if loan.sector == "Agriculture" and scenario.agricultural_shock < AGRI_SHOCK_TRIGGER:
            return 1.0 + abs(scenario.agricultural_shock) / 100 * AGRI_SECTOR_SENSITIVITY
        if loan.sector in ("Trade", "Transport") and scenario.shilling_depreciation > DEPRECIATION_TRIGGER:
            return 1.0 + scenario.shilling_depreciation / 100
        return 1.0

    def _get_pd(self, loan: Loan, scenario: MacroScenario) -> float:
        """Scenario-adjusted probability of default for one loan."""
        base_pd = self.STAGE_PD.get(loan.ifrs9_stage, {}).get(loan.product, DEFAULT_BASE_PD)

        macro_multiplier = 1.0 + scenario.severity_score * PD_PER_SEVERITY_POINT
        lti_multiplier = self._lti_multiplier(loan)
        sector_multiplier = self._sector_multiplier(loan, scenario)

        prob_default = base_pd * macro_multiplier * lti_multiplier * sector_multiplier
        return min(prob_default, MAX_PD)

    def _get_lgd(self, loan: Loan, scenario: MacroScenario) -> float:
        """Scenario-adjusted loss given default for one loan."""
        base_lgd = self.LGD[self._classify_collateral(loan)]
        collateral_haircut = 1.0 + scenario.severity_score * LGD_PER_SEVERITY_POINT
        return min(base_lgd * collateral_haircut, MAX_LGD)

    def stress_one_loan(self, loan: Loan, scenario: MacroScenario) -> dict:
        """PD, LGD and ECL for one loan under one scenario."""
        prob_default = self._get_pd(loan, scenario)
        lgd = self._get_lgd(loan, scenario)
        ead = loan.outstanding
        ecl = prob_default * lgd * ead

        return {
            "loan_id": loan.loan_id,
            "member": loan.member_name,
            "branch": loan.branch,
            "product": loan.product,
            "sector": loan.sector,
            "outstanding": loan.outstanding,
            "stage": loan.ifrs9_stage,
            "dpd": loan.dpd,
            "pd": round(prob_default, 6),
            "lgd": round(lgd, 4),
            "ead": ead,
            "ecl": round(ecl, 2),
            "provision_rate": round(ecl / ead, 6) if ead > 0 else 0,
            "collateral_status": self._classify_collateral(loan),
            "lti": round(loan.loan_to_income, 4),
        }

    def summarise_group(self, rows: list) -> dict:
        """Count, outstanding, ECL and provision rate for a list of loan results."""
        outstanding = sum(r["outstanding"] for r in rows)
        ecl = sum(r["ecl"] for r in rows)
        provision_rate = ecl / outstanding if outstanding > 0 else 0
        return {
            "count": len(rows),
            "outstanding": outstanding,
            "ecl": ecl,
            "provision_rate": provision_rate,
        }

    def summarise_by(self, loan_results: list, column: str) -> dict:
        """One summary per distinct value of `column` (product, branch or sector)."""
        summary = {}
        for value in sorted(set(r[column] for r in loan_results)):
            rows = [r for r in loan_results if r[column] == value]
            summary[value] = self.summarise_group(rows)
        return summary

    def summarise_stages(self, loan_results: list, total_outstanding: float) -> dict:
        """Same summary per IFRS 9 stage, plus average PD and LGD and share of the portfolio."""
        stage_summary = {}
        for stage in [1, 2, 3]:
            rows = [r for r in loan_results if r["stage"] == stage]
            summary = self.summarise_group(rows)
            summary["avg_pd"] = np.mean([r["pd"] for r in rows]) if rows else 0
            summary["avg_lgd"] = np.mean([r["lgd"] for r in rows]) if rows else 0
            summary["pct_of_portfolio"] = (
                summary["outstanding"] / total_outstanding if total_outstanding > 0 else 0
            )
            stage_summary[f"Stage {stage}"] = summary
        return stage_summary

    def top_10_concentration(self, loan_results: list, total_outstanding: float) -> float:
        """Share of total outstanding held by the ten largest loans."""
        if total_outstanding <= 0:
            return 0
        balances = sorted([r["outstanding"] for r in loan_results], reverse=True)
        largest_ten = balances[:10]
        return sum(largest_ten) / total_outstanding

    def run_scenario(self, scenario: MacroScenario) -> dict:
        """Run one scenario over the active loans and summarise the losses."""
        loan_results = [self.stress_one_loan(loan, scenario) for loan in self.active]
        total_outstanding = sum(l.outstanding for l in self.active)
        total_ecl = sum(r["ecl"] for r in loan_results)

        portfolio_metrics = {
            "scenario": scenario.name,
            "probability": scenario.probability,
            "severity_score": round(scenario.severity_score, 2),
            "total_loans": len(loan_results),
            "total_outstanding": total_outstanding,
            "total_ecl": total_ecl,
            "aggregate_provision_rate": total_ecl / total_outstanding if total_outstanding > 0 else 0,
            "top_10_concentration": self.top_10_concentration(loan_results, total_outstanding),
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
            "stages": self.summarise_stages(loan_results, total_outstanding),
            "products": self.summarise_by(loan_results, "product"),
            "branches": self.summarise_by(loan_results, "branch"),
            "sectors": self.summarise_by(loan_results, "sector"),
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

        base_outstanding = all_results["base"]["portfolio"]["total_outstanding"]
        weighted_rate = weighted_ecl / base_outstanding if base_outstanding > 0 else 0

        components = {}
        for key, scenario in SCENARIOS.items():
            scenario_ecl = all_results[key]["portfolio"]["total_ecl"]
            components[key] = {
                "ecl": scenario_ecl,
                "weight": scenario.probability,
                "contribution": scenario_ecl * scenario.probability,
            }

        all_results["weighted_ecl"] = {
            "total_ecl": weighted_ecl,
            "provision_rate": weighted_rate,
            "components": components,
        }

        self.results = all_results
        return all_results


# REPORT GENERATOR

EQUITY_SHARE = 0.15       # assumed equity: 15% of outstanding loans before any losses
MIN_CAPITAL_RATIO = 0.10  # minimum equity / loans the capital test compares against


class ReportGenerator:
    """Generates formatted Excel and console reports from stress test results."""

    def __init__(self, results: dict):
        self.results = results

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

        # Capital sensitivity
        print(f"\n  CAPITAL SENSITIVITY (equity assumed {EQUITY_SHARE:.0%} of loans)")
        print(f"  {'─' * (width - 4)}")
        total_outstanding = base["total_outstanding"]
        assumed_equity = total_outstanding * EQUITY_SHARE
        for s_key, s_label in [("base", "Base"), ("adverse", "Adverse"), ("severe", "Severe")]:
            ecl = self.results[s_key]["portfolio"]["total_ecl"]
            equity_after = assumed_equity - ecl
            ratio_after = equity_after / total_outstanding if total_outstanding > 0 else 0
            if ratio_after < MIN_CAPITAL_RATIO:
                verdict = f"below {MIN_CAPITAL_RATIO:.0%} minimum"
            else:
                verdict = f"above {MIN_CAPITAL_RATIO:.0%} minimum"
            print(f"  {s_label:<12} ECL: KES {ecl:>10,.0f}  "
                  f"Equity after: KES {equity_after:>10,.0f}  "
                  f"Equity/loans: {ratio_after * 100:>5.1f}%  {verdict}")

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
            # value goes in the cell directly below its label
            value_cell = ws.cell(row=ws[cell].row + 1, column=ws[cell].column, value=value)
            value_cell.font = kpi_font

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
        sector_names = sorted(sectors, key=lambda x: sectors[x]["provision_rate"], reverse=True)
        for row_idx, sector in enumerate(sector_names, 3):
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


# MAIN EXECUTION

if __name__ == "__main__":
    print("=" * 70)
    print("  SACCO LOAN PORTFOLIO STRESS TESTING ENGINE")
    print("  Alven Yuka | CPA Finalist | Accounting Specialist, GIZ")
    print("=" * 70)

    # Generate portfolio
    print("\n[1/4] Generating synthetic SACCO portfolio...")
    generator = PortfolioGenerator(seed=42)
    portfolio = generator.generate(n_loans=2000)
    active_loans = [l for l in portfolio if l.status in ("Active", "Restructured")]
    default_loans = [l for l in portfolio if l.status == "Default"]
    active_count = len(active_loans)
    default_count = len(default_loans)
    total_outstanding = sum(l.outstanding for l in active_loans)
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
    reporter = ReportGenerator(results)
    reporter.console_report()

    # Excel report
    print("[4/4] Generating Excel report...")
    output_path = "output/sacco_stress_test_report.xlsx"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    reporter.to_excel(output_path)

    print("\nDone. All outputs generated successfully.")
