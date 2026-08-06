"""Entry point for the material cert OCR extraction pipeline."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from shared_config.sqlserver import FCC_MATERIAL_DATABASE, PROD_SERVER
from shared_utils.sqlserver import append_table, get_engine, read_table, replace_table

from . import config
from .pipeline import get_processed_files, process_file


def run(material_info, prod_engine, pdf_path, sharepoint_url, rerun_all):
    root = Path(pdf_path)
    folders = sorted(p for p in root.iterdir() if p.is_dir())
    if not folders:
        print(f'No material folders found in {pdf_path}')
        return None

    pi_indexed = material_info.set_index('material')
    processed_pdfs = (
        get_processed_files(prod_engine, table='material_cert_fcc')
        if not rerun_all
        else set()
    )
    print(f'Files already in DB: {len(processed_pdfs)}')

    all_pdfs = [
        pdf
        for folder in folders
        for pdf in sorted(folder.glob('*.pdf'))
        if str(pdf.resolve()) not in processed_pdfs
    ]
    if not all_pdfs:
        print('No new PDFs for process.')
        return None

    print(
        f'Found {len(all_pdfs)} new PDF file(s) in {len(folders)} folder(s) requiring processing...'
    )

    results = []
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS_PDF) as executor:
        futures = {
            executor.submit(
                process_file, pdf, pi_indexed, pdf_path, sharepoint_url
            ): pdf
            for pdf in all_pdfs
        }
        for future in futures:
            df = future.result()
            if not df.empty:
                results.append(df)

    df_all = pd.concat(results, ignore_index=True) if results else pd.DataFrame()

    print(
        f'\n{"=" * 64}\nTOTAL: {len(df_all)} records from {len(all_pdfs)} PDF(s)\n{"=" * 64}'
    )

    if not df_all.empty:
        df_all = df_all.sort_values(['material', 'pdf_path', 'sublot']).reset_index(
            drop=True
        )
        df_all['mfg_date'] = pd.to_datetime(df_all['mfg_date']).dt.normalize()
        df_all['segment'] = df_all['segment'].str.title()
        print('Writing to DB...')

    return df_all


def main():
    parser = argparse.ArgumentParser(
        description='OCR material cert PDFs and load results into SQL Server.'
    )
    parser.add_argument(
        '--test', action='store_true', help='Use test PDFs instead of production PDFs.'
    )
    parser.add_argument(
        '--rerun-all',
        action='store_true',
        help='Re-run all PDFs instead of only new ones.',
    )
    args = parser.parse_args()

    pdf_path = config.get_pdf_path(test=args.test)

    prod_engine = get_engine(PROD_SERVER, FCC_MATERIAL_DATABASE)
    material_info = read_table(prod_engine, 'SELECT * FROM dbo.material_info')

    df_all = run(
        material_info, prod_engine, pdf_path, config.SHAREPOINT_URL, args.rerun_all
    )

    if df_all is None or df_all.empty:
        print('No new files to analyze: skipping DB write')
    elif args.rerun_all:
        replace_table(df_all, table_name='material_cert_fcc', engine_name=prod_engine)
    else:
        append_table(df_all, table_name='material_cert_fcc', engine_name=prod_engine)


if __name__ == '__main__':
    main()
