"""
Parse the 'Part History' sheet of RCCA_Summary.xlsx into tidy pandas DataFrames.

Sheet layout:
  - Row 1  : Panel Name        (columns C.. = one column per panel)
  - Row 2  : Design or PN
  - Row 3  : WOSN
  - Rows 4-175 : attribute rows, organized into sections. A row is a
    SECTION HEADER if its column-B cell is bold + font size >= 14. Everything
    below a header, until the next header, belongs to that section. Some
    header rows *also* carry a value themselves (e.g. "CPT",
    "Heated Debulk 1 (Cycle)" holds the recipe name) - captured as the
    section's own field.
  - Row 98 "ACTUALS" is a header with no value of its own; it flips a Phase
    flag from "Spec" to "Actual" for everything below it, because the same
    section/field names (Heated Debulk 1, Cure, Vac, HUR, Tiso...) reappear
    as recorded actuals.
  - Some sections repeat a field name more than once within the same section
    (e.g. Cure (Cycle) has 4 separate HUR/Tiso/Tiso Time ramp stages). These
    are disambiguated by a stable per-row occurrence suffix (_1, _2, ...)
    computed once from row order, NOT per panel, so every panel maps the
    same physical row to the same column.

Outputs:
  - long_df : one row per (Panel, Phase, Section, Field, row) -- tidy/EAV.
              Load this into a normalized SQL table (fact_part_history_attr).
  - wide_df : one row per Panel, one column per Phase__Section__Field(_n).
              Flat table for Power BI DirectQuery / ad-hoc filtering.
"""

from pathlib import Path
import re
import pandas as pd
from openpyxl import load_workbook

SRC = Path("/mnt/user-data/uploads/1788472837109_RCCA_Summary.xlsx")
SHEET = "Part History"

LABEL_COL = 2
FIRST_PANEL_COL = 3
FIRST_DATA_ROW = 2
LAST_DATA_ROW = 175


def _is_section_header(cell) -> bool:
    f = cell.font
    return bool(f.bold) and (f.sz or 0) >= 14


def _slug(text) -> str:
    text = str(text).strip()
    text = (text.replace("#", "num").replace("%", "pct")
                .replace("°", "deg").replace("\n", " "))
    text = re.sub(r"[^\w]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _build_row_schema(ws) -> list[dict]:
    """One entry per data row (4..175): row, phase, section, field, col_name."""
    schema = []
    current_section = None
    phase = "Spec"
    occurrence = {}  # (phase, section, field) -> count seen so far

    for r in range(4, LAST_DATA_ROW + 1):
        label_cell = ws.cell(r, LABEL_COL)
        label = label_cell.value
        if label is None:
            continue

        if str(label).strip().upper() == "ACTUALS":
            phase = "Actual"
            current_section = None
            continue

        is_header = _is_section_header(label_cell)
        if is_header:
            current_section = label

        field = label
        section = current_section if current_section else label

        key = (phase, section, field)
        occurrence[key] = occurrence.get(key, 0) + 1
        n = occurrence[key]

        base = f"{_slug(phase)}__{_slug(section)}__{_slug(field)}"
        col_name = base if n == 1 else f"{base}_{n}"

        schema.append({
            "row": r, "phase": phase, "section": section,
            "field": field, "col_name": col_name,
        })

    # second pass: rename ALL occurrences (including the first) to have a
    # numeric suffix whenever a field repeats >1 time in the same section,
    # so "Vac_1"/"Vac_2" both exist rather than a bare "Vac" + "Vac_2".
    counts = {}
    for e in schema:
        key = (e["phase"], e["section"], e["field"])
        counts[key] = counts.get(key, 0) + 1
    for e in schema:
        key = (e["phase"], e["section"], e["field"])
        if counts[key] == 1:
            e["col_name"] = f"{_slug(e['phase'])}__{_slug(e['section'])}__{_slug(e['field'])}"

    # final safety net: two DIFFERENT raw labels can still collide after
    # slugging (e.g. "Cure" header vs "Cure #" both slug toward "Cure").
    # Force uniqueness by appending the row number to any collision.
    seen = {}
    for e in schema:
        seen.setdefault(e["col_name"], []).append(e)
    for name, entries in seen.items():
        if len(entries) > 1:
            for e in entries:
                e["col_name"] = f"{name}__r{e['row']}"
    return schema


def parse_part_history(path: Path = SRC, sheet: str = SHEET) -> tuple[pd.DataFrame, pd.DataFrame]:
    wb = load_workbook(path, data_only=True)
    ws = wb[sheet]

    panel_cols = [c for c in range(FIRST_PANEL_COL, ws.max_column + 1) if ws.cell(1, c).value is not None]
    panel_names = {c: ws.cell(1, c).value for c in panel_cols}

    identity = {c: {
        "panel_name": panel_names[c],
        "design_or_pn": ws.cell(2, c).value,
        "wosn": ws.cell(3, c).value,
    } for c in panel_cols}

    schema = _build_row_schema(ws)

    records = []
    for e in schema:
        r = e["row"]
        for c in panel_cols:
            val = ws.cell(r, c).value
            if val is None:
                continue
            records.append({
                "panel_col": c,
                "panel_name": panel_names[c],
                "phase": e["phase"],
                "section": e["section"],
                "field": e["field"],
                "row": r,
                "col_name": e["col_name"],
                "value": val,
            })

    long_df = pd.DataFrame.from_records(records).drop(columns="panel_col")

    ident_df = pd.DataFrame.from_dict(identity, orient="index")
    ident_df.index.name = "panel_col"
    ident_df = ident_df.reset_index()

    long_df_pc = pd.DataFrame.from_records(records)  # keep panel_col for the pivot merge key
    wide_df = long_df_pc.pivot_table(
        index="panel_col", columns="col_name", values="value", aggfunc="first"
    ).reset_index()
    wide_df = ident_df.merge(wide_df, on="panel_col", how="left").drop(columns="panel_col")

    return long_df, wide_df


if __name__ == "__main__":
    long_df, wide_df = parse_part_history()
    print("long_df:", long_df.shape)
    dup_check = long_df.groupby(["panel_name", "col_name"]).size()
    print("max rows per (panel, col_name) after fix:", dup_check.max())
    print("wide_df:", wide_df.shape)
    print(wide_df["panel_name"].tolist()[:5])
    cure_cols = [c for c in wide_df.columns if "cure_cycle" in c.lower()]
    print(cure_cols)


# ---------------------------------------------------------------------------
# SQL Server load (swap the engine builder for your shared_config.sqlserver
# helper — left generic here since I don't have that module's signature).
# ---------------------------------------------------------------------------
def load_to_sql_server(long_df: pd.DataFrame, wide_df: pd.DataFrame, engine, schema: str = "dbo"):
    """
    long_df -> stg_part_history_attr   (EAV, NVARCHAR values, full fidelity, cheap to reload)
    wide_df -> dim_panel_attributes    (one row per panel, all columns as-is;
                                         let SQL Server infer NVARCHAR(MAX)/object
                                         cast, then hand-type just the handful of
                                         columns you actually aggregate on)
    """
    long_df.to_sql("stg_part_history_attr", engine, schema=schema,
                    if_exists="replace", index=False, chunksize=1000)
    wide_df_sql = wide_df.copy()
    wide_df_sql.columns = [c.lower() for c in wide_df_sql.columns]
    wide_df_sql.to_sql("dim_panel_attributes", engine, schema=schema,
                        if_exists="replace", index=False, chunksize=1000)
