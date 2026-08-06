"""
Thickness-by-month pipeline: Solumina work order data joined with material_cert_fcc
CCPT values to compute an average monthly thickness value for each material
"""

import argparse
import json
from pathlib import Path

import pandas as pd
from shared_config.sqlserver import FCC_MATERIAL_DATABASE, PROD_SERVER
from shared_utils.sqlserver import get_engine, replace_table
from sqlalchemy import create_engine, text

CREDENTIALS_PATH = Path(__file__).parent / 'credentials.json'

SAP_LOT_DATA_PATH = r'C:\analytics-work\production\extract-material-cert-fcc\data\AS - ASBU FCC Engineering - CertDataFiles\SAP_Lot_Data.xlsx'

DEFAULT_MATERIALS = [
    'LMAMA001FR49GRACL1-INCH',
    'LMAMB002FR49ST1-INCH',
]

SOLUMINA_QUERY = """
    SELECT DISTINCT
        o.PART_NO,
        s.SERIAL_NO,
        o.ORDER_NO,
        op.OPER_NO,
        op.ACTUAL_END_DATE,
        op.OPER_STATUS,
        o.ACTUAL_END_DATE AS WOCLOSE,
        CASE
            WHEN op.ACTUAL_END_DATE IS NULL THEN op.TIME_STAMP
            ELSE op.ACTUAL_END_DATE
        END AS CLOSE_DATE,
        op.TITLE,
        bom.PART_NO AS MATPART,
        bom.LOT_NO,
        bom.SPOOL_NO,
        bom.PART_QTY
    FROM SFMFG.SFWID_OPER_DESC op
    INNER JOIN SFMFG.SFWID_ORDER_DESC o
        ON op.ORDER_ID = o.ORDER_ID
    INNER JOIN SFMFG.SFWID_SERIAL_DESC s
        ON o.ORDER_ID = s.ORDER_ID
    INNER JOIN SFMFG.SFWID_AS_WORKED_BOM bom
        ON s.ORDER_ID = bom.ORDER_ID
    WHERE o.PART_NO LIKE '2WSH%'
        AND (o.ORDER_NO LIKE '00100%' OR o.ORDER_NO LIKE '34F14%')
        AND op.OPER_STATUS NOT IN ('PENDING')
        AND op.TITLE = 'Cut Comp Plies'
        AND bom.PART_NO LIKE :material
    ORDER BY CLOSE_DATE
"""


# Connect to Solumina Database (Oracle)
def load_credentials(path=CREDENTIALS_PATH):
    with Path.open(path) as file:
        return json.load(file)


def get_oracle_engine(credentials_path=CREDENTIALS_PATH):
    """Create SQLAlchemy engine for the Solumina database"""
    creds = load_credentials(credentials_path)
    url = (
        f'oracle+oracledb://{creds["solumina_user"]}:{creds["solumina_password"]}'
        f'@{creds["solumina_host"]}:{creds["solumina_port"]}/?service_name={creds["solumina_service_name"]}'
    )
    return create_engine(url)


def fetch_solumina_data(oracle_engine, material):
    """Pull raw Cut Comp Plies work order / roll data from Solumina for material"""
    df = pd.read_sql(text(SOLUMINA_QUERY), oracle_engine, params={'material': material})
    df.columns = df.columns.str.lower()
    return df


# SAP Mapping (from SAP_Lot_Data.xlsx)
def load_batch_to_vendor_lot(material, path=SAP_LOT_DATA_PATH):
    """
    Read SAP_Lot_Data.xlsx '<material>_Rolls sheet (maintained by FCC engineer) and
    return a {Batch: Supplier Batch} mapping (SAP internal batch -> vendor_lot)
    """
    sheet_name = f'{material}_Rolls'
    df = pd.read_excel(path, sheet_name=sheet_name)
    df = df[['Batch', 'Supplier Batch']].dropna(subset=['Batch'])
    return dict(zip(df['Batch'], df['Supplier Batch'], strict=True))


# Transform and aggregate data
def build_lot_summary(df, material_info):
    """Read material information into a dataframe"""
    if df.empty or df['ccpt'].isna().all():
        return pd.DataFrame()

    g = (
        df.dropna(subset=['ccpt'])
        .groupby(['material', 'vendor_lot'], as_index=False)
        .agg(ccpt_lot_avg=('ccpt', 'mean'), n_sublots=('ccpt', 'size'))
    )

    g['ccpt_lot_avg'] = g['ccpt_lot_avg'].round(8)

    pi_indexed = material_info.set_index('material')
    g['cpt_target_pos'] = g['material'].map(
        lambda m: pi_indexed.loc[m, 'cpt_target_pos'] if m in pi_indexed.index else None
    )
    g['cpt_target_neg'] = g['material'].map(
        lambda m: pi_indexed.loc[m, 'cpt_target_neg'] if m in pi_indexed.index else None
    )
    g['in_range'] = g.apply(
        lambda r: (
            None
            if pd.isna(r['cpt_target_pos'])
            else bool(r['cpt_target_neg'] <= r['ccpt_lot_avg'] <= r['cpt_target_pos'])
        ),
        axis=1,
    )
    return g


def build_row_level_ccpt(solumina_df, batch_to_vendor_lot, lot_summary, material):
    """
    Add vendor_lot, material, and ccpt to each Solumina_row -- one row per
    roll/spool. Assume solumina_df is already filtered to this material
    """
    df = solumina_df.copy()

    df['material'] = material
    df['comp_ply'] = (df['oper_status'] != 'EXCLUDE').astype(int)
    df['month_year'] = pd.to_datetime(df['close_date']).dt.strftime('%Y-%m')

    df['vendor_lot'] = df['lot_no'].map(batch_to_vendor_lot)

    ccpt_lookup = lot_summary.set_index('vendor_lot')['ccpt_lot_avg']
    df['ccpt'] = df['vendor_lot'].map(ccpt_lookup)

    missing = df['ccpt'].isna().sum()
    if missing:
        print(
            f'[{material}] WARNING: {missing} roll(s) had no CCPT match (unmapped vendor_lot or missing from lot_summary).'
        )

    return df


def build_monthly_summary(row_df, material):
    """Aggregate row-level CCPT/CompPly data to one record per month for material"""
    valid_rows = row_df.dropna(subset=['ccpt'])
    return (
        valid_rows.groupby('month_year', as_index=False)
        .agg(
            avg_ccpt=('ccpt', 'mean'),
            comp_ply_rate=('comp_ply', 'mean'),
            n_rows=('order_no', 'count'),
        )
        .assign(material=material)
        .sort_values('month_year')
        .reset_index(drop=True)
    )


# Run
def run(materials, oracle_engine, material_info, material_cert_df):
    all_summaries = []

    for material in materials:
        solumina_df = fetch_solumina_data(oracle_engine, material)
        batch_to_vendor_lot = load_batch_to_vendor_lot(material)

        cert_for_material = material_cert_df[material_cert_df['material'] == material]
        lot_summary = build_lot_summary(cert_for_material, material_info)

        row_df = build_row_level_ccpt(
            solumina_df, batch_to_vendor_lot, lot_summary, material
        )
        all_summaries.append(build_monthly_summary(row_df, material))

    return pd.concat(all_summaries, ignore_index=True)


def main():
    parser = argparse.ArgumentParser(
        description='Build the thickness-by-month summary and write data into SQL Server table'
    )
    parser.add_argument(
        '--material',
        action='append',
        dest='materials',
        help='Material to process in the thickness-by-month step (repeatable). Defaults to the built-in list.',
    )
    args = parser.parse_args()
    materials = args.materials or DEFAULT_MATERIALS

    prod_engine = get_engine(PROD_SERVER, FCC_MATERIAL_DATABASE)
    material_info = pd.read_sql('SELECT * FROM dbo.material_info', prod_engine)
    material_cert_df = pd.read_sql('SELECT * FROM dbo.material_cert_fcc', prod_engine)
    oracle_engine = get_oracle_engine()

    combined_monthly_summary = run(
        materials, oracle_engine, material_info, material_cert_df
    )
    replace_table(
        combined_monthly_summary,
        table_name='monthly_summary_fcc',
        engine_name=prod_engine,
    )


if __name__ == '__main__':
    main()
