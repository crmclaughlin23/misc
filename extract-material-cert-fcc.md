# extract-material-cert-fcc

Extracts material lot data from FCC material certification PDFs via OCR and writes per-sublot records to SQL Server.

## Overview

Scans FCC cert PDFs (many are scanned/photocopied with no text layer), locates the lot-info and in-process pages using the PDF's text layer where available or a Tesseract OCR fallback, and pulls per-sublot RC-AVG / FAW-AVG values. Vendor lot number is resolved by cross-checking the filename against OCR text. For each sublot, calculated cured ply thickness (CCPT) is computed using resin/fiber density looked up from `material_info`.

The pipeline is still a notebook prototype: `main.py` is the unmodified `uv init` stub, and the working logic lives in `notebooks/extract_material_cert_fcc.ipynb`.

## Data sources

- `material_info` table — PROD_SERVER / FCC_MATERIAL_DATABASE — resin/fiber density and CPT targets per material
- Cert PDFs — `\\ut02sa1\programs\JSF\Engineering\Materials\MaterialLotData\MaterialCertData\CertDataFiles` (or `CertDataFiles_Test` when the `test` toggle is `True`)

## Outputs

- `material_cert_fcc` table — PROD_SERVER / FCC_MATERIAL_DATABASE — one row per sublot (material, vendor_lot, mfg_date, location, sublot, segment, rc, faw, ccpt, is_picked, source_file)

## Usage

Run the notebook directly (`uv run jupyter lab`, select the `monorepo` kernel). Two toggles near the top control behavior:

- `test` — use test PDFs instead of production PDFs
- `rerun_all` — reprocess every PDF (replaces the SQL table) vs. only new ones (appends)

Requires Poppler and Tesseract OCR installed locally; paths are set in the notebook and are currently hardcoded to one machine.

## Status

Still in `development/` — not yet migrated from the notebook into `main.py`.
