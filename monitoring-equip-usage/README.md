# monitoring-equip-usage

Builds equipment usage tables from the CPC_* pyrometry databases: historical Runs/Parts/Uptime data, and a live current-status snapshot per piece of equipment.

## Overview

**Historical build** (`equip_usage/historical.py`) queries every `CPC_*` database in parallel for raw `Runs`, `RealtimeData` summary, and `Parts` data, then builds:
- `runs_data` — one row per cure run, enriched with equipment alt-names, Avg_Duration (median by Equipment/Recipe/RecipeRevision), Aborted flag, CureToCure/DoorToDoor gaps, and PartCount
- `parts_data` — per-part detail rows
- `uptime_data` — each run expanded into per-day uptime/downtime minutes, with gaps between cures filled in as idle days

**Current-status build** (`equip_usage/current_status.py`) queries every `CPC_*` database in parallel for the latest `RealtimeData` row (TOP 1 by `DataTime`), then builds:
- `current_equip_status` — one row per equipment, with a `TimeLeft` estimate computed against Avg_Duration
- `sorting_table` — display ordering (alphabetic prefix + numeric suffix) for equipment names

The current-status build needs an Avg_Duration lookup (one row per Equipment+Recipe) to compute `TimeLeft`. In `--mode all`, it uses the runs_data just built. In `--mode current-status` (standalone), it reads that lookup back from the `EquipUsage_Runs` SQL table instead, so it doesn't need to rebuild history to run.

## Data sources

- `[Equipment PCs]` table — PROD_SERVER / Pyrometry — equipment/site lookup and alt-name mapping (two different join keys are used against it: `Equip` for the historical build, `DAT_Name` for current-status, matching two different raw Equipment identifiers)
- `CPC_*` databases on the pyrometry server — `dbo.Runs`, `dbo.RealtimeData`, `dbo.Parts` (schema varies slightly db-to-db; `Press` and `PurgeStatus` columns aren't present everywhere and are detected per-database)

## Outputs

All tables written to PROD_SERVER / Pyrometry, replacing on each run:
- `EquipUsage_Runs`, `EquipUsage_Parts`, `EquipUsage_Uptime` — historical build
- `EquipUsage_Live`, `EquipUsage_Sorting` — current-status build

## Usage

```powershell
uv run main.py                        # both stages
uv run main.py --mode historical      # runs_data / parts_data / uptime_data only
uv run main.py --mode current-status  # live snapshot only, reads Avg_Duration from EquipUsage_Runs
```

## Known issue carried over from the notebook

In `historical.build_uptime_data`, the gap-filling loop (filling idle days between consecutive cures) uses a `Site` value left over from the last row of the prior loop rather than the site of the specific gap being filled. Ported as-is rather than silently fixed, since fixing it changes output. Worth a decision on whether to correct it.

## Status

Newly converted from `notebooks/equip_usage.ipynb`. Needs a run against real data to verify before moving to `production/`.
