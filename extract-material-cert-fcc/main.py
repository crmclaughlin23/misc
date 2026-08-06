"""Runs the material certification OCR extraction, followed by the average monthly material thickness calculations."""

import argparse

import pandas as pd
from extraction import config as extract_config
from extraction.main import run as run_extraction
from shared_config.sqlserver import FCC_MATERIAL_DATABASE, PROD_SERVER
from shared_utils.sqlserver import append_table, get_engine, read_table, replace_table
from thickness_by_month import DEFAULT_MATERIALS, get_oracle_engine
from thickness_by_month import run as run_thickness


def main():
    parser = argparse.ArgumentParser(
        description='Run material cert OCR extraction, then rebuild the thickness-by-month table.'
    )
    parser.add_argument(
        '--rerun-all',
        action='store_true',
        help='Re-run all PDFs in the extraction step.',
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
    material_info = read_table(prod_engine, 'SELECT * FROM dbo.material_info')

    # Material cert OCR extraction
    pdf_path = extract_config.get_pdf_path()
    df_all = run_extraction(
        material_info,
        prod_engine,
        pdf_path,
        extract_config.SHAREPOINT_URL,
        args.rerun_all,
    )

    if df_all is None or df_all.empty:
        print('No new material cert files to analyze: skipping DB write')
    elif args.rerun_all:
        replace_table(df_all, table_name='material_cert_fcc', engine_name=prod_engine)
    else:
        append_table(df_all, table_name='material_cert_fcc', engine_name=prod_engine)

    # Thickness-by-month calculations
    material_cert_df = pd.read_sql('SELECT * FROM material_cert_fcc', prod_engine)
    oracle_engine = get_oracle_engine()

    combined_monthly_summary = run_thickness(
        materials, oracle_engine, material_info, material_cert_df
    )
    replace_table(
        combined_monthly_summary,
        table_name='monthly_summary_fcc',
        engine_name=prod_engine,
    )

    print('\nDone.')


if __name__ == '__main__':
    main()
