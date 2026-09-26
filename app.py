from flask import Flask, render_template, request, jsonify

from calculator import SimInputs, simulate, summarize, chart_payload
from zipdata import lookup_zip

app = Flask(__name__)


DEFAULTS = {
    "home_price": 385000,
    "down_payment": 75000,
    "mortgage_rate_pct": 7.0,
    "n_years": 30,
    "monthly_rent": 2100,
    "available_capital": 150000,
    "investment_return_pct": 4.0,
    "property_tax_rate_pct": 1.0,
    "hoa": 500,
    "home_appreciation_pct": 1.5,
    "rent_growth_pct": 2.5,
    "moving_cost": 3000,
    "closing_costs": 5000,
    "realtor_fees": 0,
    # Ownership costs the first version omitted. Defaults are standard rules of thumb.
    "maintenance_rate_pct": 1.0,
    "insurance_rate_pct": 0.45,
    "pmi_rate_pct": 0.5,
    "selling_cost_pct": 6.0,
    # Tax deduction. marginal_tax_rate_pct = 0 turns it off. Standard deduction default is
    # married-filing-jointly (2025); use ~15,000 for single.
    "marginal_tax_rate_pct": 0.0,
    "standard_deduction": 30000,
    "salt_cap": 10000,
    "other_itemized": 0,
}


def _to_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _build_inputs(payload: dict) -> SimInputs:
    g = lambda k: _to_float(payload.get(k), DEFAULTS[k])
    return SimInputs(
        home_price=g("home_price"),
        down_payment=g("down_payment"),
        mortgage_rate=g("mortgage_rate_pct") / 100.0,
        n_years=int(g("n_years")),
        monthly_rent=g("monthly_rent"),
        available_capital=g("available_capital"),
        investment_return=g("investment_return_pct") / 100.0,
        property_tax_rate=g("property_tax_rate_pct") / 100.0,
        hoa=g("hoa"),
        home_appreciation=g("home_appreciation_pct") / 100.0,
        rent_growth=g("rent_growth_pct") / 100.0,
        moving_cost=g("moving_cost"),
        closing_costs=g("closing_costs"),
        realtor_fees=g("realtor_fees"),
        maintenance_rate=g("maintenance_rate_pct") / 100.0,
        insurance_rate=g("insurance_rate_pct") / 100.0,
        pmi_rate=g("pmi_rate_pct") / 100.0,
        selling_cost_pct=g("selling_cost_pct") / 100.0,
        marginal_tax_rate=g("marginal_tax_rate_pct") / 100.0,
        standard_deduction=g("standard_deduction"),
        salt_cap=g("salt_cap"),
        other_itemized=g("other_itemized"),
    )


# Every input, with the metadata the sensitivity UI needs: a label, how to format it, and a
# sensible default sweep range. `kind` drives both the axis formatting and the step size.
DIMENSIONS = [
    {"key": "home_price",            "label": "Home price",            "kind": "money", "lo": 0.7, "hi": 1.3},
    {"key": "down_payment",          "label": "Down payment",          "kind": "money", "lo": 0.3, "hi": 2.0},
    {"key": "mortgage_rate_pct",     "label": "Mortgage rate",         "kind": "pct",   "abs": (3.0, 9.0)},
    {"key": "n_years",               "label": "Loan term (years)",     "kind": "int",   "abs": (10, 30)},
    {"key": "monthly_rent",          "label": "Monthly rent",          "kind": "money", "lo": 0.6, "hi": 1.6},
    {"key": "available_capital",     "label": "Available capital",     "kind": "money", "lo": 0.5, "hi": 2.0},
    {"key": "investment_return_pct", "label": "Investment return",     "kind": "pct",   "abs": (2.0, 10.0)},
    {"key": "property_tax_rate_pct", "label": "Property tax rate",     "kind": "pct",   "abs": (0.3, 2.5)},
    {"key": "hoa",                   "label": "HOA / monthly fees",    "kind": "money", "abs": (0, 1200)},
    {"key": "home_appreciation_pct", "label": "Home appreciation",     "kind": "pct",   "abs": (0.0, 6.0)},
    {"key": "rent_growth_pct",       "label": "Rent growth",           "kind": "pct",   "abs": (0.0, 6.0)},
    {"key": "moving_cost",           "label": "Moving cost",           "kind": "money", "abs": (0, 15000)},
    {"key": "closing_costs",         "label": "Closing costs",         "kind": "money", "abs": (0, 30000)},
    {"key": "realtor_fees",          "label": "Realtor fees",          "kind": "money", "abs": (0, 30000)},
    {"key": "maintenance_rate_pct",  "label": "Maintenance",           "kind": "pct",   "abs": (0.0, 2.5)},
    {"key": "insurance_rate_pct",    "label": "Insurance",             "kind": "pct",   "abs": (0.0, 1.5)},
    {"key": "pmi_rate_pct",          "label": "PMI rate",              "kind": "pct",   "abs": (0.0, 1.5)},
    {"key": "selling_cost_pct",      "label": "Selling costs",         "kind": "pct",   "abs": (0.0, 10.0)},
    {"key": "marginal_tax_rate_pct", "label": "Marginal tax rate",     "kind": "pct",   "abs": (0.0, 45.0)},
    {"key": "standard_deduction",    "label": "Standard deduction",    "kind": "money", "abs": (0, 40000)},
    {"key": "salt_cap",              "label": "SALT cap",              "kind": "money", "abs": (0, 40000)},
    {"key": "other_itemized",        "label": "Other itemized",        "kind": "money", "abs": (0, 40000)},
]
DIM_BY_KEY = {d["key"]: d for d in DIMENSIONS}

METRICS = [
    {"key": "delta",       "label": "Buy vs Rent — who ends ahead"},
    {"key": "crossover",   "label": "Crossover year"},
    {"key": "house_final", "label": "Buying: final wealth"},
    {"key": "apt_final",   "label": "Renting: final wealth"},
]

MAX_STEPS = 11          # per axis; 11 x 11 = 121 sims, well under a second


def _axis_values(dim_key: str, lo: float, hi: float, steps: int) -> list:
    steps = max(2, min(int(steps), MAX_STEPS))
    if hi == lo:
        return [lo]
    out = [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]
    if DIM_BY_KEY.get(dim_key, {}).get("kind") == "int":
        out = sorted({int(round(v)) for v in out})
    return out


@app.route("/")
def index():
    return render_template("index.html", defaults=DEFAULTS, dimensions=DIMENSIONS, metrics=METRICS)


@app.route("/api/zip/<zipcode>")
def api_zip(zipcode):
    """Suggested inputs for a ZIP, each tagged with where it came from."""
    try:
        return jsonify(lookup_zip(zipcode))
    except Exception as e:  # never break the page over a lookup
        return jsonify({"zip": zipcode, "fields": {}, "place": None,
                        "warnings": [f"Lookup failed: {e}"]})


@app.route("/api/grid", methods=["POST"])
def api_grid():
    """Sensitivity over one or two arbitrary inputs.

    Returns a 1-D series (one variable) or a 2-D matrix (two), for the chosen metric. Each cell
    is a full simulation with only the swept inputs overridden.
    """
    payload = request.get_json(silent=True) or {}
    base_payload = {k: payload.get(k, DEFAULTS[k]) for k in DEFAULTS}
    metric = payload.get("metric", "delta")

    v1 = payload.get("var1") or {}
    v2 = payload.get("var2") or None
    k1 = v1.get("key")
    if k1 not in DIM_BY_KEY:
        return jsonify({"error": "pick a first variable"}), 400
    xs = _axis_values(k1, _to_float(v1.get("min")), _to_float(v1.get("max")), v1.get("steps", 7))

    k2 = (v2 or {}).get("key")
    ys = None
    if k2 and k2 in DIM_BY_KEY and k2 != k1:
        ys = _axis_values(k2, _to_float(v2.get("min")), _to_float(v2.get("max")), v2.get("steps", 7))

    def cell(over: dict):
        inp = _build_inputs({**base_payload, **over})
        df = simulate(inp)
        s = summarize(df, inp)
        if metric == "crossover":
            # None means it never crosses within the horizon — keep it null so the chart shows a gap
            return s["crossover_year"]
        if metric == "house_final":
            return s["house_final"]
        if metric == "apt_final":
            return s["apt_final"]
        return s["delta"]

    if ys is None:
        values = [cell({k1: x}) for x in xs]
        return jsonify({"mode": "1d", "metric": metric, "x": xs, "x_label": DIM_BY_KEY[k1]["label"],
                        "x_kind": DIM_BY_KEY[k1]["kind"], "values": values})

    z = [[cell({k1: x, k2: y}) for x in xs] for y in ys]
    return jsonify({"mode": "2d", "metric": metric,
                    "x": xs, "x_label": DIM_BY_KEY[k1]["label"], "x_kind": DIM_BY_KEY[k1]["kind"],
                    "y": ys, "y_label": DIM_BY_KEY[k2]["label"], "y_kind": DIM_BY_KEY[k2]["kind"],
                    "z": z})


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    payload = request.get_json(silent=True) or {}
    inp = _build_inputs(payload)
    df = simulate(inp)
    return jsonify({
        "summary": summarize(df, inp),
        "chart": chart_payload(df),
    })


@app.route("/api/sensitivity", methods=["POST"])
def api_sensitivity():
    """Sweep down payment and return the final-asset curve for each."""
    payload = request.get_json(silent=True) or {}
    base = _build_inputs(payload)

    home_price = base.home_price
    sweeps = []
    # Five evenly-spaced down payment scenarios from 5% to 50% of home price
    for pct in [0.05, 0.10, 0.20, 0.35, 0.50]:
        dp = round(home_price * pct, -3)
        if dp >= base.available_capital:
            continue
        scenario = SimInputs(**{**base.__dict__, "down_payment": dp})
        df = simulate(scenario)
        sweeps.append({
            "label": f"{int(pct*100)}% down (${dp:,.0f})",
            "down_payment": dp,
            "house_total": df["HOUSE_Total_Capital+Equity"].round(2).tolist(),
            "final": float(df.iloc[-1]["HOUSE_Total_Capital+Equity"]),
        })

    months = list(range(0, base.n_years * 12 + 1))
    return jsonify({"months": months, "scenarios": sweeps})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
