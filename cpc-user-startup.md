# cpc-user-startup

Restarts the CPC application on a user PC with fresh objects, recipes, and QC cards.

## Overview

Stops `CPCClient` and `CPCObjServer`, copies the latest `Objects.g` file, CPC recipes, and QC cards into the local CPC folders, then relaunches `CPCClient`. Temporarily renames `AppPath.txt` during the update so the running client doesn't lock it, then restores it afterward.

## Data sources

- `Objects.g` — `\\ut02sf6\Group1\Public\CPC\FCC`
- CPC recipes — `C:\CPC Recipes`
- QC cards — `C:\CPCQCards`

## Outputs

- Refreshed `Objects.g`, recipes, and QC cards under `C:\CPC\...`
- Restarted `CPCClient.exe`

## Usage

```powershell
uv run main.py
```
