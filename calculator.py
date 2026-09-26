"""
Rent vs. Buy financial simulation.

Models, beyond the original notebook: maintenance, homeowners insurance, PMI while the loan is
above 80% LTV, selling costs charged against equity at every period, and the mortgage-interest /
SALT deduction (only the part that clears the standard deduction).

Mirrors the logic from the original notebook (sim_table) with two small fixes:
  - The notebook referenced `rent_growth` in the function body but declared
    `rent_increase_percent` as the parameter; we standardize on `rent_growth`.
  - Property tax is treated consistently as a rate (e.g. 0.01 = 1%) applied to
    the *current* home value each month, not a fixed dollar amount.
"""

from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd


def _accumulate(start: float, contributions: np.ndarray, rate: float) -> np.ndarray:
    """x[k] = x[k-1]*(1+rate) + contributions[k], solved in closed form.

    Discount each contribution, cumulative-sum, then compound back — exactly the same numbers
    as the month-by-month loop, without the per-row Python."""
    k = np.arange(len(contributions), dtype=float)
    growth = (1.0 + rate) ** k
    c = contributions.copy()
    c[0] = 0.0
    return growth * (start + np.cumsum(c / growth))


@dataclass
class SimInputs:
    home_price: float
    down_payment: float
    mortgage_rate: float           # annual, decimal (e.g. 0.07)
    n_years: int
    monthly_rent: float
    available_capital: float
    investment_return: float       # annual, decimal
    property_tax_rate: float       # annual rate on home value, decimal
    hoa: float                     # monthly $
    home_appreciation: float       # annual, decimal
    rent_growth: float             # annual, decimal
    moving_cost: float
    closing_costs: float
    realtor_fees: float

    # --- ownership costs the first version omitted (all bias the answer toward buying) ---
    maintenance_rate: float = 0.0   # annual, on current home value (rule of thumb: 1%)
    insurance_rate: float = 0.0     # annual, on current home value (~0.4-0.5% typical)
    pmi_rate: float = 0.0           # annual, on the outstanding balance, while LTV > 80%
    selling_cost_pct: float = 0.0   # commission + seller closing, charged on the sale price

    # --- mortgage interest / SALT deduction ---
    # The benefit is NOT interest x rate. It is the marginal rate applied only to the amount by
    # which itemized deductions EXCEED the standard deduction — which for most households after
    # the 2017 SALT cap + higher standard deduction is zero. Set marginal_tax_rate to 0 to skip.
    marginal_tax_rate: float = 0.0  # combined federal + state marginal rate, decimal
    standard_deduction: float = 0.0 # filing-status standard deduction ($ / yr)
    salt_cap: float = 10_000.0      # cap on deductible state+local (incl. property) tax
    other_itemized: float = 0.0     # charitable etc. ($ / yr), helps clear the standard deduction


def simulate(inp: SimInputs) -> pd.DataFrame:
    n = inp.n_years * 12
    loan = max(inp.home_price - inp.down_payment, 0.0)
    r = inp.mortgage_rate / 12

    if loan > 0 and r > 0:
        mortgage_pmt = loan * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    elif loan > 0:
        mortgage_pmt = loan / n
    else:
        mortgage_pmt = 0.0

    df = pd.DataFrame({"period": range(0, n + 1)})

    # Home value compounding monthly
    df["HOUSE_Value"] = inp.home_price * (1 + inp.home_appreciation / 12) ** df["period"]
    df["HOUSE_Value_Increase"] = df["HOUSE_Value"] - inp.home_price
    df["HOUSE_Mortgage"] = mortgage_pmt

    # Amortization
    # Amortization in closed form (identical to the month-by-month recurrence, ~100x faster):
    #   balance_k = L(1+r)^k - P((1+r)^k - 1)/r
    k = df["period"].to_numpy(dtype=float)
    if loan > 0 and r > 0:
        growth = (1.0 + r) ** k
        end_balance = loan * growth - mortgage_pmt * (growth - 1.0) / r
    elif loan > 0:                      # 0% loan: straight-line principal
        end_balance = loan - mortgage_pmt * k
    else:
        end_balance = np.zeros_like(k)
    end_balance = np.maximum(end_balance, 0.0)

    beg_balance = np.empty_like(end_balance)
    beg_balance[0] = 0.0
    beg_balance[1:] = end_balance[:-1]

    interest = np.zeros_like(end_balance)
    interest[1:] = beg_balance[1:] * r
    principal = np.zeros_like(end_balance)
    principal[1:] = mortgage_pmt - interest[1:]

    df["Beg_Balance"] = beg_balance
    df["Interest_Paid"] = interest
    df["Principal_Paid"] = principal
    df["End_Balance"] = end_balance
    df["Total_Equity"] = inp.down_payment + np.cumsum(principal)

    df["Total_Equity"] += df["HOUSE_Value_Increase"]

    df["HOUSE_HOA"] = inp.hoa
    df["HOUSE_Taxes"] = df["HOUSE_Value"] * inp.property_tax_rate / 12
    # Maintenance and insurance scale with the home, like taxes — a flat dollar amount would
    # understate both badly over a 30-year horizon.
    df["HOUSE_Maintenance"] = df["HOUSE_Value"] * inp.maintenance_rate / 12
    df["HOUSE_Insurance"] = df["HOUSE_Value"] * inp.insurance_rate / 12
    # PMI runs until the balance drops below 80% of the ORIGINAL price (the statutory
    # auto-termination point), not 80% of the appreciated value.
    df["HOUSE_PMI"] = 0.0
    if inp.pmi_rate > 0:
        over_80 = df["End_Balance"] > 0.8 * inp.home_price
        df.loc[over_80, "HOUSE_PMI"] = df.loc[over_80, "End_Balance"] * inp.pmi_rate / 12

    df["HOUSE_Total_Monthly_Costs"] = (
        df["HOUSE_Mortgage"] + df["HOUSE_HOA"] + df["HOUSE_Taxes"]
        + df["HOUSE_Maintenance"] + df["HOUSE_Insurance"] + df["HOUSE_PMI"]
    )

    # --- tax benefit, computed per 12-month block then spread across its months ---
    df["HOUSE_Tax_Benefit"] = 0.0
    if inp.marginal_tax_rate > 0:
        year = ((df["period"] - 1) // 12).clip(lower=0)
        interest_by_year = df.groupby(year)["Interest_Paid"].transform("sum")
        tax_by_year = df.groupby(year)["HOUSE_Taxes"].transform("sum")
        itemized = interest_by_year + tax_by_year.clip(upper=inp.salt_cap) + inp.other_itemized
        excess = (itemized - inp.standard_deduction).clip(lower=0)
        df["HOUSE_Tax_Benefit"] = excess * inp.marginal_tax_rate / 12
        df.loc[0, "HOUSE_Tax_Benefit"] = 0.0

    # What owning actually costs after the deduction — this is what the comparison uses.
    df["HOUSE_Net_Monthly_Cost"] = df["HOUSE_Total_Monthly_Costs"] - df["HOUSE_Tax_Benefit"]

    # Rent steps up annually
    df["APT_Rent"] = float("nan")
    annual_mask = df["period"] % 12 == 0
    df.loc[annual_mask, "APT_Rent"] = (
        inp.monthly_rent * (1 + inp.rent_growth) ** (df.loc[annual_mask, "period"] / 12)
    )
    df["APT_Rent"] = df["APT_Rent"].ffill()

    # If owning is cheaper than renting in a given month, the difference is
    # contributed to the buyer's investment account.
    df["HOUSE_Monthly_Savings_Compared_to_APT"] = (df["APT_Rent"] - df["HOUSE_Net_Monthly_Cost"]).clip(lower=0)

    inv_r = inp.investment_return / 12
    house_start = (
        inp.available_capital - (inp.down_payment + inp.moving_cost + inp.closing_costs + inp.realtor_fees)
    )
    df["HOUSE_Total_Capital"] = _accumulate(
        house_start, df["HOUSE_Monthly_Savings_Compared_to_APT"].to_numpy(dtype=float), inv_r
    )

    # Equity you could actually walk away with: selling costs are charged at every period, so the
    # crossover point reflects "if I sold today", not just the final year.
    df["HOUSE_Selling_Costs"] = df["HOUSE_Value"] * inp.selling_cost_pct
    df["HOUSE_Net_Equity"] = df["Total_Equity"] - df["HOUSE_Selling_Costs"]
    df["HOUSE_Total_Capital+Equity"] = df["HOUSE_Total_Capital"] + df["HOUSE_Net_Equity"]

    # Renting side: start with full capital, invest the surplus when rent is
    # cheaper than total ownership cost.
    df["APT_Monthly_Savings_Compared_to_House"] = (df["HOUSE_Net_Monthly_Cost"] - df["APT_Rent"]).clip(lower=0)
    df["APT_Total_Assets"] = _accumulate(
        inp.available_capital, df["APT_Monthly_Savings_Compared_to_House"].to_numpy(dtype=float), inv_r
    )

    return df


def summarize(df: pd.DataFrame, inp: SimInputs) -> dict:
    final = df.iloc[-1]
    house_final = float(final["HOUSE_Total_Capital+Equity"])
    apt_final = float(final["APT_Total_Assets"])

    # Crossover: first month buying overtakes renting
    diff = df["HOUSE_Total_Capital+Equity"] - df["APT_Total_Assets"]
    crossover_period = None
    if (diff > 0).any() and (diff <= 0).any():
        crossover_period = int(diff[diff > 0].index[0])

    return {
        "house_final": house_final,
        "apt_final": apt_final,
        "delta": house_final - apt_final,
        "winner": "Buying" if house_final >= apt_final else "Renting",
        "crossover_month": crossover_period,
        "crossover_year": round(crossover_period / 12, 1) if crossover_period is not None else None,
        "monthly_mortgage": float(df.loc[1, "HOUSE_Mortgage"]) if len(df) > 1 else 0.0,
        "first_month_house_cost": float(df.loc[1, "HOUSE_Total_Monthly_Costs"]) if len(df) > 1 else 0.0,
        "upfront_cash": float(inp.down_payment + inp.moving_cost + inp.closing_costs + inp.realtor_fees),
        "n_periods": len(df),
        "selling_costs": float(final["HOUSE_Selling_Costs"]),
        "tax_benefit_total": float(df["HOUSE_Tax_Benefit"].sum()),
        "tax_benefit_first_year": float(df.loc[1:12, "HOUSE_Tax_Benefit"].sum()) if len(df) > 12 else 0.0,
        "maintenance_total": float(df["HOUSE_Maintenance"].sum()),
        "insurance_total": float(df["HOUSE_Insurance"].sum()),
        "pmi_total": float(df["HOUSE_PMI"].sum()),
        "pmi_months": int((df["HOUSE_PMI"] > 0).sum()),
    }


def chart_payload(df: pd.DataFrame) -> dict:
    """Compact JSON for the front-end (we only need a subset)."""
    months = df["period"].tolist()
    return {
        "months": months,
        "years": [m / 12 for m in months],
        "house_total": df["HOUSE_Total_Capital+Equity"].round(2).tolist(),
        "apt_total": df["APT_Total_Assets"].round(2).tolist(),
        "house_equity": df["Total_Equity"].round(2).tolist(),
        "house_investments": df["HOUSE_Total_Capital"].round(2).tolist(),
        "house_value": df["HOUSE_Value"].round(2).tolist(),
        "house_monthly_cost": df["HOUSE_Total_Monthly_Costs"].round(2).tolist(),
        "house_net_monthly_cost": df["HOUSE_Net_Monthly_Cost"].round(2).tolist(),
        "house_net_equity": df["HOUSE_Net_Equity"].round(2).tolist(),
        "rent_monthly": df["APT_Rent"].round(2).tolist(),
    }
