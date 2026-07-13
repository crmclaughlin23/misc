# report-3dp-requests

Extracts 3DP request and material cost data from SharePoint list exports and writes it to SQL Server for the Power BI report.

## Overview

Loads the `3DP Request - Clearfield UT` and `Cost Estimator Values` SharePoint list exports, cleans and enriches the request data (business days to complete, time to approval, on-time status), and parses cost columns into per-material/per-machine effective cost per unit (applying unit conversions and Objet yield factors). Results are written to SQL Server for Power BI.

`notebooks/get_3dp_lists.ipynb` contains the same pipeline logic in notebook form, kept around for interactive exploration.

## Data sources

- SharePoint list exports (JSON) in `data/` — `3DP Request - Clearfield UT` and `Cost Estimator Values`, produced by a Power Automate flow
- `references/3DP Material Costs.csv` — reference cost data

## Outputs

- `printing.material_cost`, `printing.request`, `printing.request_cost` tables — PROD_SERVER / PYRO_DATABASE

## Usage

```powershell
uv run main.py
```

Or via the scheduled trigger:

```powershell
triggers/report-3dp-requests.ps1
```
