# list-of-cpc-recipes

Lists all CPC recipe files into a formatted Excel workbook.

## Overview

Walks the CPC recipes network folder, records each recipe file's folder/subfolder path, and writes a sorted, formatted Excel sheet (auto-filter, borders, auto-sized columns). Opens the workbook automatically when finished.

## Data sources

- `\\ut02sa7\ac\Recipes` — CPC recipes folder

## Outputs

- `All Recipes.xlsx` — one row per recipe file, with `Folder`, `Folder\Subfolder`, and `File` columns

## Usage

```powershell
uv run main.py
```

Triggered via `triggers/list_cpc_recipes.bat`.
