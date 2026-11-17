"""Settings for report-3dp-requests."""

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / 'data'

LOCAL_TZ = 'America/Denver'
SCHEMA = 'printing'

# SharePoint list display names (must match the ListName in the Power Automate flow)
LISTS = {
    'requests': '3DP Request - Clearfield UT',
    'costs': 'Cost Estimator Values',
    'volumes': 'Printer Build Volumes',
}

# Date the legacy list was migrated; rows created on it use 'Legacy Created time'
MIGRATION_DATE = '2025-01-31'

# Status stages, in workflow order
STAGES = [
    'Quote Accepted D&T',
    'Quote Sent D&T',
    'Approved/In Queue D&T',
    'Printing D&T',
    'Printing Off Site D&T',
    'Post Processing D&T',
    'On Hold D&T',
    'Complete D&T',
]

# Average material per part (job size) bins
SIZE_BINS = [0, 5, 10, 25, 50, 100, float('inf')]
SIZE_LABELS = ['< 5', '5-10', '10-25', '25-50', '50-100', '> 100']

# Cost conversion factors
IN3_TO_CC = 16.3871
CC_TO_IN3 = 1 / IN3_TO_CC
OBJET_YIELD = {
    'VeroClear': 1.19,
    'VeroYellow': 1.18,
    'Agilus30 Black': 1.15,
}
OBJET_FIXED_MULTIPLIER = 2.0
