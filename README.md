# Rent vs. Buy

A long-horizon rent-vs-buy simulation. Both paths are compared on the same monthly budget:
whichever option is cheaper in a given month, the difference is invested at your expected return.
That's what makes the two final numbers comparable.

Ported from `docs/original_notebook.ipynb`, then extended — see **Methodology** below.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py            # http://127.0.0.1:5001
```

Port 5001, not 5000 — macOS AirPlay squats on 5000 and answers 403.

## Deploy (EC2, gunicorn + nginx)

```bash
# on the box
git clone <your remote> ~/rent_v_buy && cd ~/rent_v_buy
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

sudo cp deploy/rentvbuy.service /etc/systemd/system/rentvbuy.service
sudo systemctl daemon-reload && sudo systemctl enable --now rentvbuy

sudo cp deploy/rentvbuy.nginx.conf /etc/nginx/sites-available/rentvbuy
sudo ln -sf /etc/nginx/sites-available/rentvbuy /etc/nginx/sites-enabled/rentvbuy
sudo nginx -t && sudo systemctl reload nginx
```

Set `server_name` in the nginx config, then `sudo certbot --nginx -d yourdomain` for TLS.

**Sharing a box with TackTracker?** That app already uses gunicorn `:8000` and holds nginx's
`default_server` on :80. This one is configured for `:8001` and needs a real `server_name`
(a subdomain pointed at the box) — nginx rejects two `default_server` blocks on the same port.

Notes for the box:
- Paths in both config files assume `/home/ubuntu/rent_v_buy`. Change them if you deploy elsewhere.
- The first ZIP lookup downloads ~124 MB from Zillow and takes ~10s; it's cached in `data/`
  (gitignored) for 30 days. Give the instance a little disk headroom, or pre-warm it with
  `python3 -c "import zipdata; zipdata.lookup_zip('22314')"` after deploying.
- No API keys, no secrets, no database. Nothing to configure.

## What it models

| Renting | Owning |
|---|---|
| Rent, rising annually | Mortgage (real amortization schedule) |
| Whole capital stays invested | Down payment + closing/moving/buyer-agent fees out of capital |
| Investment growth, compounded monthly | Property tax, HOA, maintenance, insurance, PMI |
| Invests the surplus when renting is cheaper | Home appreciation and equity |
| | Selling costs, netted off equity **at every period** |
| | Mortgage interest + property tax deduction, only above the standard deduction |
| | Invests the surplus when owning is cheaper |

Not modelled: inflation on HOA/fees, tax on investment gains, the primary-residence capital-gains
exclusion, renter-side costs (deposits, renter's insurance, moving between rentals).

## Methodology notes

- **Equity** = down payment + principal paid + appreciation, which is algebraically the same as
  home value − loan balance.
- **The comparison needs no discounting.** Both sides end at the same date in nominal dollars, and
  the investment return already plays the role of the discount rate — compounding cash flows at
  `r` is equivalent to discounting at `r`. Adding explicit discounting would double-count.
- **PMI** is charged until the balance falls below 80% of the *purchase price* (the statutory
  auto-termination point), not 80% of the appreciated value.
- **The tax deduction is not `interest × rate`.** It's the marginal rate applied only to the amount
  by which itemized deductions exceed the standard deduction, with property tax capped by SALT.
  For many households post-2017 that is legitimately $0, and the model says so.
- **Known inconsistency:** HOA is flat forever while rent grows, and maintenance/insurance/tax
  track home value rather than general inflation. Both quietly favour buying. A single inflation
  input would fix it — not yet built.

## ZIP grounding

`zipdata.py` fills in real numbers for a ZIP, from free keyless sources:

| Field | Source | Kind |
|---|---|---|
| Home price | Zillow ZHVI, that ZIP | measured |
| Home appreciation | Zillow ZHVI 5-year growth, that ZIP | measured |
| Monthly rent | Zillow ZORI, that ZIP | measured |
| Rent increases | Zillow ZORI 5-year growth, that ZIP | measured |
| Property tax | bundled state-average table | **estimated** |
| City / state | Zippopotam.us | — |

Every value carries its source and date in the UI, and state-average estimates are labelled as
such — county rates vary a lot within a state.

## Layout

```
app.py          Flask routes: /, /api/simulate, /api/sensitivity, /api/grid, /api/zip
calculator.py   the simulation (vectorized; ~7 ms per 30-year run)
zipdata.py      ZIP lookups + the Zillow cache
wsgi.py         gunicorn entry point
templates/      one page
static/         css + js (Plotly from CDN)
docs/           the original notebook this came from
deploy/         systemd unit + nginx site
```
