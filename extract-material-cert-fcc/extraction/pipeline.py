"""Per-file orchestration for the material cert OCR pipeline."""

from pathlib import Path
from urllib.parse import quote

import pandas as pd

from . import config
from .ocr import _ocr_many, find_relevant_pages
from .parsing import (
    extract_inprocess,
    extract_lot_info,
    extract_picked_sublots,
    resolve_vendor_lot,
)


def file_to_sharepoint_url(file, pdf_path, sharepoint_url):
    """
    Build the SharePoint URL for a PDF from its local path under pdf_path.

    Assumes pdf_path is a local OneDrive shortcut to the SharePoint folder at
    sharepoint_url -- the two must point to the same folder level so the
    relative paths line up.
    """
    rel_path = Path(file).resolve().relative_to(Path(pdf_path).resolve())
    rel_url = quote(str(rel_path).replace('\\', '/'))
    return f'{sharepoint_url}/{rel_url}'


def get_processed_files(engine, table='material_cert_fcc'):
    """Return a set of pdf_path values already in SQL table."""
    try:
        df = pd.read_sql(f'SELECT DISTINCT pdf_path FROM [{table}]', engine)
        return set(df['pdf_path'].dropna())
    except Exception:
        return set()


def process_file(file, pi_indexed, pdf_path, sharepoint_url):
    """Two-pass OCR a single cert PDF. Returns a DataFrame of per-sublot rows."""
    print(f'\n  Processing {Path(file).name} ...')

    pages = find_relevant_pages(file, config.LOW_DPI)
    if not pages['in_process']:
        retry = config.LOW_DPI + 50
        print(
            f'    No in-process pages at {config.LOW_DPI} DPI, retrying at {retry} DPI...'
        )
        pages = find_relevant_pages(file, retry)
        if not pages['in_process']:
            print(f'    Still none; skipping {Path(file).name}.')
            return pd.DataFrame()

    lot_text = _ocr_many(
        file, pages['lot_info'], config.HIGH_DPI, config.LOT_INFO_CONFIG
    )
    proc_text = _ocr_many(file, pages['in_process'], config.HIGH_DPI, config.OCR_CONFIG)
    page_text = {**lot_text, **proc_text}

    lot: dict[str, str | None] = {
        'material': None,
        'vendor_lot': None,
        'mfg_date': None,
        'location': None,
    }
    picked = set()

    for pn in pages['lot_info']:
        if page_text.get(pn):
            lot = extract_lot_info(page_text[pn], pi_indexed)
            lot['vendor_lot'] = resolve_vendor_lot(file, page_text[pn])
            picked = extract_picked_sublots(page_text[pn])
            break

    rows = []
    for pn in pages['in_process']:
        if page_text.get(pn):
            rows.extend(extract_inprocess(page_text[pn]))

    if not rows:
        print('    No sublot RC/FAW rows extracted.')
        return pd.DataFrame()

    material_info_row = (
        pi_indexed.loc[lot['material']] if lot['material'] in pi_indexed.index else None
    )
    if material_info_row is None:
        print(
            f'    WARNING: "{lot["material"]}" not in material_info -- CCPT will be blank.'
        )

    resin = (
        material_info_row['resin_density'] if material_info_row is not None else None
    )
    fiber = (
        material_info_row['fiber_density'] if material_info_row is not None else None
    )

    out = []
    for r in rows:
        norm = (r['sublot'].lstrip('0') or '0').upper()
        rec = {
            'material': lot['material'],
            'vendor_lot': lot['vendor_lot'],
            'mfg_date': lot['mfg_date'],
            'location': lot['location'],
            'sublot': r['sublot'],
            'segment': r['segment'],
            'rc': r['rc'],
            'faw': r['faw'],
            'ccpt': None,
            'is_picked': 1 if (picked and norm in picked) else 0,
            'pdf_path': str(Path(file).resolve()),
            'pdf_url': file_to_sharepoint_url(file, pdf_path, sharepoint_url),
        }
        if resin and fiber and r['rc'] is not None and r['faw'] is not None:
            rc, faw = r['rc'], r['faw']
            rec['ccpt'] = round(
                (faw / 25400) * ((1 / fiber) + ((rc / 100) / ((1 - rc / 100) * resin))),
                8,
            )
        out.append(rec)

    df = pd.DataFrame(out)
    if df['mfg_date'].notna().any():
        df['mfg_date'] = pd.to_datetime(df['mfg_date'], errors='coerce')
    print(f'    Extracted {len(df)} sublot records.')
    return df
