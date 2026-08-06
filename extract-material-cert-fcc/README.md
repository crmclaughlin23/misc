# extract-material-cert-fcc

Extracts material lot data from FCC material certification PDFs via OCR, then rolls the resulting CCPT values up into a thickness-by-month summary using Solumina (Oracle) work order data. Both stages write to SQL Server.

## Overview

**Material cert OCR extraction** scans FCC cert PDFs (many are scanned/photocopied with no text layer), locates the lot-info and in-process pages using the PDF's text layer where available or a Tesseract OCR fallback, and pulls per-sublot RC-AVG / FAW-AVG values. Vendor lot number is resolved by cross-checking the filename against OCR text. For each sublot, calculated cured ply thickness (CCPT) is computed using resin/fiber density looked up from `material_info`.

**Thickness-by-month rollup** queries Solumina (Oracle SFMFG schema) for Cut Comp Plies work order data, maps SAP batch numbers to vendor lots via the client-maintained `SAP_Lot_Data.xlsx`, joins against the extracted CCPT data, computes a quantity-weighted CCPT per work order, and rolls up to a monthly summary per material.

`main.py` runs both stages in sequence: extraction writes to `material_cert_fcc` first, then the rollup reads that table fresh -- including anything the extraction step just wrote -- before building the monthly summary.

## Data sources

- `material_info` table — PROD_SERVER / FCC_MATERIAL_DATABASE — resin/fiber density and CPT targets per material
- Cert PDFs — `data/AS - ASBU FCC Engineering - CertDataFiles/` (OneDrive-synced from SharePoint)
- `data/.../SAP_Lot_Data.xlsx` — client-maintained SAP batch export; one `<material>_Rolls` sheet per material, each with `Batch` and `Supplier Batch` columns
- Solumina (Oracle, SFMFG schema) — Cut Comp Plies work order / roll data

## Outputs

- `material_cert_fcc` table — PROD_SERVER / FCC_MATERIAL_DATABASE — one row per sublot (material, vendor_lot, mfg_date, location, sublot, segment, rc, faw, ccpt, is_picked, pdf_path, pdf_url)
- `monthly_summary_fcc` table — PROD_SERVER / FCC_MATERIAL_DATABASE — one row per (material, month)

## Usage

Run the full pipeline:
```powershell
uv run main.py
uv run main.py --rerun-all
```

- `--rerun-all` — reprocess every PDF in the extraction step (replaces `material_cert_fcc`) vs. only new ones (appends)

Run either step standalone:
```powershell
uv run python -m extraction.main --rerun-all
uv run python thickness_by_month.py
```

Requires Poppler and Tesseract OCR installed locally; paths are set in `extraction/config.py` and are currently hardcoded to one machine.

## Status

Still in `development/` — has been migrated from notebook to `main.py`, but monitoring before moving to `production/`.
