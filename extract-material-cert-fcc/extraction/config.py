"""Configuration constants for the material certification OCR pipeline"""

import re

PROJECT_PATH = r'C:\analytics-work\production\extract-material-cert-fcc'

PROD_PDF_PATH = r'C:\analytics-work\production\extract-material-cert-fcc\data\AS - ASBU FCC Engineering - CertDataFiles'

OUTPUT_PATH = rf'{PROJECT_PATH}\output\fcc_material_cert_data.xlsx'

SHAREPOINT_URL = (
    'https://ngc.sharepoint.us/teams/AS-ASBUFCCEngineering/'
    'Shared%20Documents/General/FCC%20Pre%20Cure/MaterialLotData/CertDataFiles'
)

POPPLER_PATH = r'C:\Program Files\poppler\Library\bin'
TESSERACT_PATH = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

LOW_DPI = 160
HIGH_DPI = 275
OCR_CONFIG = r'--oem 3 --psm 6'
LOT_INFO_CONFIG = r'--oem 1 --psm 6'
MAX_WORKERS_PDF = 8
MAX_WORKERS_PAGE = 1

VENDOR_LOT_PATTERN = re.compile(r'^(?=.*[A-Z])(?=.*\d)[A-Z0-9]{5,7}$')


def get_pdf_path(test: bool = False) -> str:
    """Return the PDF root folder."""
    return PROD_PDF_PATH
