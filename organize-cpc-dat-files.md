# organize-cpc-dat-files

Organizes and cleans CPC cure `.DAT` files on the shared Z-drive.

## Overview

Optionally copies `.DAT` files from each equipment PC's local CPC/ASC data folder, then sorts every `.DAT` file in the destination into per-site and per-equipment subfolders (by year) based on filename patterns. Copies a shared `Target.DAT` into every subfolder that's missing one, then deletes `.DAT` files older than the cutoff date from each folder.

## Data sources

- `Equipment PCs` table — PROD_SERVER / PYRO_DATABASE
- `.DAT` files from `C:\CPC Data` / `C:\ASC Data` on each equipment PC (only copied when `COPY_FILES_FROM_SOURCE = True`)

## Outputs

- Organized `.DAT` files under `\\ut02sa7\ac\Data\<Site>\...` and `\<Equipment>\...` (plus a `493` folder for HC/SAT/TUS variants)
- Old files (>30 days, or before 2017 for `493`) deleted from each folder

## Usage

```powershell
uv run main.py
```

Triggered via `triggers/organize-cpc-dat-files.ps1`.
