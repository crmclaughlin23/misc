"""OCR helpers and page classification for the material cert pipeline."""

from concurrent.futures import ThreadPoolExecutor

import pypdf
import pytesseract
from pdf2image import convert_from_path, pdfinfo_from_path

from . import config

pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_PATH


def _ocr_page(file, page_num, dpi, config_str=config.OCR_CONFIG):
    """Render one 1-indexed page to an image and OCR it. Returns (page_num, text)."""
    imgs = convert_from_path(
        file,
        dpi=dpi,
        poppler_path=config.POPPLER_PATH,
        first_page=page_num,
        last_page=page_num,
    )
    if not imgs:
        return page_num, ''
    return page_num, pytesseract.image_to_string(imgs[0], config=config_str)


def _ocr_many(file, page_numbers, dpi, config_str=config.OCR_CONFIG):
    """OCR a set of pages in parallel. Returns {page_num: text}."""
    page_numbers = sorted(set(page_numbers))
    if not page_numbers:
        return {}
    if len(page_numbers) == 1:
        pn, text = _ocr_page(file, page_numbers[0], dpi, config_str)
        return {pn: text}
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS_PAGE) as ex:
        out = {
            pn: text
            for pn, text in ex.map(
                lambda p: _ocr_page(file, p, dpi, config_str), page_numbers
            )
        }  # noqa: C416
    return out


def _classify_pages_from_text(page_texts):
    """Given {page_num: text}, return {'lot_info': [...], 'in_process': [...]}."""
    pages = {'lot_info': [], 'in_process': []}
    for pn in sorted(page_texts):
        lower = (page_texts[pn] or '').lower()
        if 'customer part number' in lower or 'picked rolls' in lower:
            pages['lot_info'].append(pn)
        if 'in process' in lower and ('rc-avg' in lower or 'sublot:' in lower):
            pages['in_process'].append(pn)
    return pages


def _find_relevant_pages_text_layer(file):
    """Use pypdf text layer to locate relevant pages. Returns None if the PDF
    has no text layer (i.e. it's a scan and needs OCR)."""
    try:
        reader = pypdf.PdfReader(file)
    except Exception as e:
        print(f'    pypdf could not open file: {e}; falling back to OCR scan.')
        return None

    texts = {}
    any_text = False
    for pn, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ''
        if text.strip():
            any_text = True
        texts[pn] = text

    if not any_text:
        return None
    return _classify_pages_from_text(texts)


def _find_relevant_pages_ocr(file, dpi_value=config.LOW_DPI):
    """Low-DPI OCR scan of every page. Used as fallback when text layer fails."""
    n_pages = pdfinfo_from_path(file, poppler_path=config.POPPLER_PATH)['Pages']
    texts = _ocr_many(file, range(1, n_pages + 1), dpi_value)
    return _classify_pages_from_text(texts)


def find_relevant_pages(file, dpi_value=config.LOW_DPI):
    """Locate lot-info and in-process pages. Text layer preferred, OCR fallback."""
    pages = _find_relevant_pages_text_layer(file)
    if pages is not None and pages['in_process']:
        return pages
    return _find_relevant_pages_ocr(file, dpi_value)
