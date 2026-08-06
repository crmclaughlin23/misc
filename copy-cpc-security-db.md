# copy-cpc-security-db

Copies the correct `SecurityDatabase.mdb` to each CPC equipment PC.

## Overview

Looks up the list of equipment PCs from SQL Server, maps each equipment/site to its correct security database source, and copies `SecurityDatabase.mdb` from the shared source into the local CPC install path (`CPC Client` or `CPC ObjServer`) on each reachable PC. PCs that can't be reached are skipped and logged.

## Data sources

- `Equipment PCs` table — PROD_SERVER / PYRO_DATABASE
- `SecurityDatabase.mdb` — `\\ut02sa7\ac\User\<Database>\`

## Outputs

- Updated `SecurityDatabase.mdb` copied to each equipment PC's local CPC folder

## Usage

```powershell
uv run main.py
```

Called from CPC via `triggers/cpc_copy_security_dbs.bat`.
