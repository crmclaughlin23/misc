import argparse
import re
from pathlib import Path

import pandas as pd

SHEET = 'Power Query'


def to_snake_case(text) -> str:
    text = str(text).strip().lower()
    text = text.replace('#', ' number').replace('%', ' pct').replace('°', ' deg')
    text = re.sub(r'[^a-z0-9]+', '_', text)
    return re.sub(r'_+', '_', text).strip('_')


def load_raw_data(path: Path, sheet: str) -> pd.DataFrame:
    # keep_default_na=False: pandas treats "N/A" as missing by default, but it's a real value here
    raw_data = pd.read_excel(path, sheet_name=sheet, header=0, keep_default_na=False, na_values=[])
    raw_data = raw_data.replace('', pd.NA)
    raw_data.index.name = 'source_row'
    return raw_data.reset_index()


def get_panel_columns(raw_data: pd.DataFrame) -> list[str]:
    # Excel's used-range extends past the real data, so pandas invents "Unnamed: N" columns -- drop them
    return [c for c in raw_data.columns if c not in ('source_row', 'Section', 'Description')
            and not str(c).startswith('Unnamed')]


def build_column_names(raw_data: pd.DataFrame) -> pd.Series:
    # section-qualify only fields that repeat across DIFFERENT sections (e.g. "Vac" in every cycle section)
    sections_per_description = raw_data.groupby('Description')['Section'].transform('nunique')
    is_ambiguous = sections_per_description > 1
    field_name = raw_data['Description'].map(to_snake_case)
    section_name = raw_data['Section'].map(to_snake_case)
    column_name = field_name.where(~is_ambiguous, section_name + '_' + field_name)

    # same field can also repeat WITHIN one section (Cure Cycle has 4 Tiso ramp stages) -- number those
    occurrence_number = raw_data.groupby(['Section', 'Description']).cumcount() + 1
    column_name = column_name.where(occurrence_number == 1, column_name + '_' + occurrence_number.astype(str))

    # different raw labels can still collide after formatting -- fall back to the source row
    duplicate_name_mask = column_name.duplicated(keep=False)
    return column_name.mask(duplicate_name_mask, column_name + '_row' + (raw_data['source_row'] + 2).astype(str))


def build_column_index(raw_data: pd.DataFrame) -> pd.DataFrame:
    return (
        raw_data[['column_name', 'Section', 'Description']]
        .drop_duplicates(subset='column_name')
        .rename(columns={'Section': 'section', 'Description': 'field'})
        .reset_index(drop=True)
    )


def melt_panel_values(raw_data: pd.DataFrame, panel_columns: list[str]) -> pd.DataFrame:
    melted = (
        raw_data.melt(id_vars=['column_name'], value_vars=panel_columns,
                       var_name='panel_column_raw', value_name='value')
        .dropna(subset=['value'])
    )
    # panel_id: position-based (sheet column number), NOT panel_name -- panel names repeat
    panel_id_by_column = {name: position + 3 for position, name in enumerate(panel_columns)}
    melted['panel_id'] = melted['panel_column_raw'].map(panel_id_by_column)
    melted['panel_name'] = melted['panel_column_raw'].str.replace(r'\.\d+$', '', regex=True)
    return melted


def parse_part_history(path: Path, sheet: str = SHEET) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_data = load_raw_data(path, sheet)
    panel_columns = get_panel_columns(raw_data)
    raw_data['column_name'] = build_column_names(raw_data)
    column_index = build_column_index(raw_data)

    melted_panel_values = melt_panel_values(raw_data, panel_columns)
    panel_history = melted_panel_values.pivot_table(
        index=['panel_id', 'panel_name'], columns='column_name', values='value', aggfunc='first'
    ).reset_index()

    # a field blank for every panel never gets a column above -- drop it from the index too
    column_index = column_index[column_index['column_name'].isin(panel_history.columns)].reset_index(drop=True)

    return panel_history, column_index


def export_to_xlsx(output: Path, panel_history: pd.DataFrame, column_index: pd.DataFrame) -> None:
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        panel_history.to_excel(writer, sheet_name='panel_history', index=False)
        column_index.to_excel(writer, sheet_name='column_index', index=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parse RCCA Part History into a Power BI-ready xlsx export')
    parser.add_argument('--source', type=Path,
                         default=Path.cwd().parent / 'resources' / 'RCCA Summary - Cody Edits.xlsx',
                         help='Path to the source workbook')
    parser.add_argument('--output', type=Path,
                         default=Path.cwd().parent / 'output' / 'part_history_export.xlsx',
                         help='Path to write the xlsx export')
    args = parser.parse_args()

    panel_history, column_index = parse_part_history(args.source)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    export_to_xlsx(args.output, panel_history, column_index)
    print(f'Wrote {args.output}')
