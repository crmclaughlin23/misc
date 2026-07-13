# report-dwo-requests

Extracts Development Work Order request data from a SharePoint list export and writes it to SQL Server for reporting.

## Overview

Loads the `Development Work Order` SharePoint list export, cleans and standardizes fields (status/program values, requestor names, HTML/whitespace cleanup on text fields), and computes on-time delivery flags (`OnTimeDiff`, `AheadOfSchedule`) from completion vs. need date. Result is written to SQL Server.

`notebooks/get_dwo_lists.ipynb` contains the same pipeline logic in notebook form, kept around for interactive exploration.

## Data sources

- SharePoint list export (JSON) in `data/` — `Development Work Order`, produced by a Power Automate flow

## Outputs

- `dwo_requests` table — PROD_SERVER / PYRO_DATABASE

## Usage

```powershell
uv run main.py
```

Or via the scheduled trigger:

```powershell
triggers/report-dwo-requests.ps1
```
