"""Vendor lot parsing and OCR text extraction for material cert PDFs."""

import re
from difflib import get_close_matches
from pathlib import Path

from . import config

_ACE_ANCHOR = re.compile(r'^(ACE|FCC)\d+$', re.IGNORECASE)
_LOT_NAME = re.compile(r'Lot Name:?\s*([A-Z0-9]{5,7})', re.IGNORECASE)
_CUSTOMER_PART_NUMBER = re.compile(
    r'Customer Part Number:?\s*([A-Z0-9\-]+)', re.IGNORECASE
)
_MFG_DATE = re.compile(
    r'Date of Manufacture:?\s*(\d{1,2}\s*-\s*[A-Za-z]{3}\s*-\s*\d{4}'
    r'|\d{1,2}\s*-\s*\d{1,2}\s*-\s*\d{4})'
)
_LOCATION = re.compile(r'([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*),\s*([A-Z]{2})\s+\d{5}')
_PICKED_ROLLS = re.compile(
    r'Picked Rolls\s*/\s*Sublots:?\s*(.+?)'
    r'(?:\n[A-Z][a-z]|\n\s*\n|APPROVED|REQUIRED|Report Number)',
    re.DOTALL | re.IGNORECASE,
)
_PICKED_TOKEN = re.compile(r'\b\d{1,4}[A-Za-z]?\b')
_SUBLOT_PATTERN = re.compile(
    r'Sublot:?\s*(\d{1,5}[A-Za-z]?)\.?\s*(?:Segment:?\s*([A-Z][A-Z ]+?))?\s*$',
    re.IGNORECASE,
)
_RC_AVG_LABEL = re.compile(r'\bRC[\-\s]*AVG\b', re.IGNORECASE)
_FAW_AVG_LABEL = re.compile(r'\bFAW[\-\s]*AVG\b', re.IGNORECASE)
_RC_VALUE_PRIMARY = re.compile(r'(\d{2}[.,]\d)')
_RC_VALUE_FALLBACK = re.compile(r'\b(\d{2})\b')
_FAW_VALUE_PRIMARY = re.compile(r'(\d{2,3}[.,]\d)')
_FAW_VALUE_FALLBACK = re.compile(r'\b(\d{2,3})\b')


def vendor_lot_from_filename(file):
    """Parse vendor_lot from filename. Returns None if pattern doesn't match.

    Filenames vary in structure but consistently contain an ACE-prefixed order
    number followed by the vendor lot. Examples:
        ACE0124043_GV0J71_3554628-400.pdf                          -> GV0J71
        1781728149156_ACE0112705_AH0NPM-Northrop_Grumman_...pdf    -> AH0NPM
    """
    stem = Path(file).stem
    tokens = re.split(r'[^A-Za-z0-9]', stem)

    pdf_idx = next((i for i, t in enumerate(tokens) if _ACE_ANCHOR.match(t)), None)

    search_tokens = tokens[pdf_idx + 1 :] if pdf_idx is not None else tokens
    for tok in search_tokens:
        candidate = tok.strip().upper()
        if config.VENDOR_LOT_PATTERN.match(candidate):
            return candidate
    return None


def resolve_vendor_lot(file, ocr_text):
    """Get vendor_lot from filename (primary) and OCR (verification)."""
    fn_lot = vendor_lot_from_filename(file)

    m = _LOT_NAME.search(ocr_text)
    ocr_lot = m.group(1).strip().upper() if m else None

    if fn_lot and ocr_lot:
        if fn_lot != ocr_lot:
            if len(fn_lot) != len(ocr_lot):
                print(
                    f'    WARNING: vendor_lot length mismatch -- filename "{fn_lot}", OCR "{ocr_lot}"'
                )
            else:
                print(
                    f'    vendor_lot OCR substitution detected: OCR "{ocr_lot}" -> filename "{fn_lot}"'
                )
        return fn_lot

    if fn_lot:
        return fn_lot
    if ocr_lot:
        print(
            f'    NOTE: vendor_lot from OCR only (filename pattern did not match): "{ocr_lot}"'
        )
        return ocr_lot

    print('    WARNING: vendor_lot could not be determined from filename or OCR')
    return None


def extract_lot_info(text, pi_indexed):
    """Extract lot-level metadata from cover page OCR text."""
    info: dict[str, str | None] = {
        'material': None,
        'vendor_lot': None,
        'mfg_date': None,
        'location': None,
    }

    m = _CUSTOMER_PART_NUMBER.search(text)
    if m:
        part = m.group(1).strip()
        known = list(pi_indexed.index)
        if part not in known:
            matches = get_close_matches(part, known, n=1, cutoff=0.9)
            if matches:
                part = matches[0]
            else:
                print(
                    f'    WARNING: material "{part}" could not be matched to any known material name'
                )
        info['material'] = part

    m = _MFG_DATE.search(text)
    if m:
        info['mfg_date'] = re.sub(r'\s*-\s*', '-', m.group(1).strip())

    m = _LOCATION.search(text)
    if m:
        info['location'] = f'{m.group(1)}, {m.group(2)}'

    return info


def extract_picked_sublots(text):
    """Parse 'Picked Rolls / Sublots:' into a normalized set for membership tests."""
    picked = set()
    m = _PICKED_ROLLS.search(text)
    if m:
        for tok in _PICKED_TOKEN.findall(m.group(1)):
            picked.add((tok.lstrip('0') or '0').upper())
    return picked


def _to_float(s):
    try:
        return float(s.replace(',', '.'))
    except (ValueError, AttributeError):
        return None


def extract_inprocess(text):
    """State machine over OCR lines -> one record per sublot with RC/FAW avg."""
    records = []
    cur = None

    def flush():
        if cur and cur['rc'] is not None and cur['faw'] is not None:
            records.append(cur.copy())

    for raw in text.split('\n'):
        line = re.sub(r'\s+', ' ', raw).strip()
        if not line:
            continue

        m = _SUBLOT_PATTERN.search(line)
        if m:
            flush()
            seg = m.group(2).strip() if m.group(2) else None
            cur = {
                'sublot': m.group(1).upper(),
                'segment': seg,
                'rc': None,
                'faw': None,
            }
            continue

        if cur is None:
            continue

        if _RC_AVG_LABEL.search(line):
            v = _RC_VALUE_PRIMARY.search(line) or _RC_VALUE_FALLBACK.search(line)
            if v:
                cur['rc'] = _to_float(v.group(1))
            continue

        if _FAW_AVG_LABEL.search(line):
            v = _FAW_VALUE_PRIMARY.search(line) or _FAW_VALUE_FALLBACK.search(line)
            if v:
                cur['faw'] = _to_float(v.group(1))
            continue

    flush()
    return records
