# report-3dp-requests

Extracts 3DP request, material cost, and printer build volume data from SharePoint list exports and writes it to SQL Server for the Power BI report.

## Overview

Loads the `3DP Request - Clearfield UT`, `Cost Estimator Values`, and `Printer Build Volumes` SharePoint list exports, cleans and enriches the request data (business days to complete, time to approval, on-time status, corrected created date), and reshapes it into job-level and child tables for Power BI. Cost columns are parsed into per-material/per-machine effective cost per unit (applying unit conversions and Objet yield factors).

`printing.request` holds one row per job. Every other `request_*` table holds only `ID` plus the columns specific to its grain; Power BI relates each to `request[ID]` (many-to-one, single direction), so slicers on `request` (dates, location, status, program) filter all of them.

## Structure

| File | Purpose |
|---|---|
| `main.py` | Entry point: load exports, build tables, write to SQL. All I/O lives here. |
| `config.py` | Data directory, SharePoint list names, schema, time zone, size bins, unit/yield factors |
| `transform.py` | DataFrame-in, DataFrame-out functions; no file or SQL I/O |
| `notebooks/explore_3dp_data.ipynb` | Interactive exploration; imports `config` and `transform` |
| `shared_utils.sharepoint` | `load_sharepoint_export` (shared across projects; needs `beautifulsoup4` in `shared_utils`) |

## Data sources

- SharePoint list exports (JSON) in `data/`, produced by a Power Automate flow:
  - `3DP Request - Clearfield UT`
  - `Cost Estimator Values`
  - `Printer Build Volumes`

## Outputs

SQL Server `PROD_SERVER` / `PYRO_DATABASE`, schema `printing`:

| Table | Grain | Key columns |
|---|---|---|
| `request` | One row per job | `ID` + all cleaned request fields |
| `request_machine` | Job × machine | `ID, Machine, Machine Build Time` |
| `request_stage` | Job × status stage (completed jobs) | `ID, stage, order, start, end, days` |
| `request_material` | Job × machine × tier × material | `ID, Machine, Material, Role, Qty` |
| `request_job_size` | Job × machine | `ID, Machine, Total Qty, Avg Qty per Part, Size Bin, Size Bin Order` |
| `material_cost` | Raw cost estimator values | — |
| `request_cost` | Material × machine | `material, machine, unit, effective_cost_per_unit, ...` |
| `build_volume` | Machine | `machine, volume` |

## Known data limitations

- Jobs created before 2025 (migrated legacy rows) have no per-material quantities, so `request_material` and `request_job_size` start in 2025.
- Machine names differ between the `Machine` field (`F450mc`, `Objet350 CNX3`, `Markforged Mark 2`) and the material column names (`F450`, `Objet`, `Markforged Mk2`).
- Quantities are in mixed units across machines (cu-in for F-series, grams for Objet/Fusion3); compare within a machine group.

## Usage

```powershell
uv run main.py
```

Or via the scheduled trigger:

```powershell
triggers/report-3dp-requests.ps1
```
