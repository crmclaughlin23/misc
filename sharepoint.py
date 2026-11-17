"""Load SharePoint list exports produced by the Power Automate flow."""

import json
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

SKIP_TYPES = {'Computed'}
RICH_TEXT_TYPES = {'Note'}
DATETIME_TYPES = {'DateTime'}
ALWAYS_KEEP = {
    'ID': ('ID', 'Counter'),
    'Created': ('Created', 'DateTime'),
    'Modified': ('Modified', 'DateTime'),
    'Author': ('Author', 'User'),
    'Editor': ('Editor', 'User'),
}


def _strip_html(text):
    """Convert HTML to plain text."""
    if not isinstance(text, str) or '<' not in text:
        return text
    return BeautifulSoup(text, 'html.parser').get_text(separator='\n').strip()


def _convert(raw, field_type):
    if raw is None:
        return None
    if field_type in ('User', 'UserMulti') and isinstance(raw, dict):
        return raw.get('DisplayName')
    if field_type in ('Lookup', 'LookupMulti') and isinstance(raw, dict):
        return raw.get('Value')
    if isinstance(raw, list):
        # Multi-value fields (multi-person, multi-lookup, multi-choice)
        return '; '.join(
            (x.get('DisplayName') or x.get('Value') or str(x)) if isinstance(x, dict) else str(x)
            for x in raw
        )
    if isinstance(raw, dict):
        return raw.get('DisplayName') or raw.get('Value') or raw.get('Title') or str(raw)
    if field_type in RICH_TEXT_TYPES:
        return _strip_html(raw)
    if field_type in DATETIME_TYPES:
        ts = pd.to_datetime(raw, utc=True, errors='coerce')
        return ts.date() if pd.notna(ts) else None
    return raw


def load_sharepoint_export(list_name, data_dir):
    """
    Load a SharePoint list export into a DataFrame with display-name columns.

    Parameters
    ----------
    list_name : str
        The SharePoint list display name (must match the ListName used
        in the Power Automate flow exactly).
    data_dir : str or Path
        Directory containing {list_name}_items.json and {list_name}_fields.json.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns named by SharePoint display names.
    """
    data_dir = Path(data_dir)
    with (data_dir / f'{list_name}_items.json').open(encoding='utf-8') as f:
        items = json.load(f)
    with (data_dir / f'{list_name}_fields.json').open(encoding='utf-8-sig') as f:
        fields = json.load(f)

    field_map = {
        f['InternalName']: (f['Title'], f['TypeAsString'])
        for f in fields
        if f['TypeAsString'] not in SKIP_TYPES
    }
    for internal_name, spec in ALWAYS_KEEP.items():
        field_map.setdefault(internal_name, spec)

    rows = []
    for item in items:
        row = {}
        for internal_name, (display_name, field_type) in field_map.items():
            raw = item.get(internal_name)
            if raw is None and internal_name.startswith('_'):
                raw = item.get(f'OData_{internal_name}')
            row[display_name] = _convert(raw, field_type)
        rows.append(row)

    return pd.DataFrame(rows)
