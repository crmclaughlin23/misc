def main():
    # Imports
    import json
    from pathlib import Path

    import numpy as np
    import pandas as pd
    from bs4 import BeautifulSoup
    from shared_config.sqlserver import PROD_SERVER, PYRO_DATABASE
    from shared_utils.sqlserver import get_engine
    from sqlalchemy.schema import CreateSchema

    # Config
    DATA_DIR = r'C:\Users\M67743\OneDrive - NGC\analytics-work\production\report-3dp-requests\data'
    REQUESTS = '3DP Request - Clearfield UT'
    # COSTS = '3DP Material Costs'
    COSTS = 'Cost Estimator Values'
    VOLUMES = 'Printer Build Volumes'

    IN3_TO_CC = 16.3871
    CC_TO_IN3 = 1 / 16.3871

    OBJET_YIELD = {
        'VeroClear': 1.19,
        'VeroYellow': 1.18,
        'Agilus30 Black': 1.15,
    }

    LOCAL_TZ = 'America/Denver'

    pyro_engine = get_engine(PROD_SERVER, PYRO_DATABASE)

    # Functions
    def _strip_html(text):
        """
        Convert HTML to plain text.
        """
        if not isinstance(text, str) or '<' not in text:
            return text
        return BeautifulSoup(text, 'html.parser').get_text(separator='\n').strip()

    def _business_days(row):
        cutover = pd.Timestamp('2025-01-31').date()

        complete = row['Complete D&T']
        if pd.isna(complete):
            return pd.NA

        created = row['Created']
        legacy = row['Legacy Created time']

        if pd.notna(created) and created > cutover:
            start_date = created
        elif pd.notna(legacy):
            start_date = legacy
        else:
            return pd.NA

        start = np.datetime64(pd.Timestamp(start_date).date(), 'D')
        end = np.datetime64(pd.Timestamp(complete).date(), 'D')

        if end < start:
            return pd.NA

        return int(np.busday_count(start, end))

    def load_sharepoint_export(list_name, data_dir):
        """
        Load a SharePoint list export into a DataFrame with display-name columns.

        Parameters
        ----------
        list_name : str
            The SharePoint list display name (must match the ListName used
            in the Power Automate flow exactly).
        data_dir : str or Path
            Directory containing the exported {list_name}_items.json and
            {list_name}_fields.json files.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns named by SharePoint display names.
        """
        data_dir = Path(data_dir)
        items_path = data_dir / f'{list_name}_items.json'
        fields_path = data_dir / f'{list_name}_fields.json'

        with Path.open(items_path, encoding='utf-8') as f:
            items = json.load(f)
        with Path.open(fields_path, encoding='utf-8-sig') as f:
            fields = json.load(f)

        # Build internal_name -> (display_name, type) mapping from the schema
        SKIP_TYPES = {'Computed'}
        field_map = {
            f['InternalName']: (f['Title'], f['TypeAsString']) 
            for f in fields
            if f['TypeAsString'] not in SKIP_TYPES
        }

        # Keep the following excluded fields
        field_map.setdefault('ID', ('ID', 'Counter'))
        field_map.setdefault('Created', ('Created', 'DateTime'))
        field_map.setdefault('Modified', ('Modified', 'DateTime'))
        field_map.setdefault('Author', ('Author', 'User'))
        field_map.setdefault('Editor', ('Editor', 'User'))

        rich_text_types = {'Note'}
        datetime_types = {'DateTime'}

        rows = []
        for item in items:
            row = {}
            for internal_name, (display_name, field_type) in field_map.items():
                raw = item.get(internal_name)
                if raw is None and internal_name.startswith('_'):
                    raw = item.get(f'OData_{internal_name}')

                if raw is None:
                    row[display_name] = None
                elif field_type in ('User', 'UserMulti') and isinstance(raw, dict):
                    row[display_name] = raw.get('DisplayName')
                elif field_type in ('Lookup', 'LookupMulti') and isinstance(raw, dict):
                    row[display_name] = raw.get('Value')
                elif isinstance(raw, list):
                    # Multi-value fields (multi-person, multi-lookup, multi-choice)
                    row[display_name] = '; '.join(
                        (x.get('DisplayName') or x.get('Value') or str(x))
                        if isinstance(x, dict)
                        else str(x)
                        for x in raw
                    )
                elif isinstance(raw, dict):
                    # Catch-all for unexpected nested objects
                    row[display_name] = (
                        raw.get('DisplayName')
                        or raw.get('Value')
                        or raw.get('Title')
                        or str(raw)
                    )
                elif field_type in rich_text_types:
                    row[display_name] = _strip_html(raw)
                elif field_type in datetime_types:
                    ts = pd.to_datetime(raw, utc=True, errors='coerce')
                    row[display_name] = ts.date() if pd.notna(ts) else None
                else:
                    row[display_name] = raw
            rows.append(row)

        return pd.DataFrame(rows)

    # Parse each column name into (material, machine, unit)
    def parse_col(col, row):
        parts = [part.strip() for part in col.split(',')]
        if len(parts) != 3:
            return [None, None, None, None, None, None, None]

        material, machine, unit = parts
        base_cost = row[col]

        conversion_factor = 1.0
        yield_factor = 1.0
        fixed_multiplier = 1.0

        if machine == 'Markforged Mk2':
            conversion_factor = CC_TO_IN3
        elif machine == 'Objet350':
            conversion_factor = IN3_TO_CC
            yield_factor = OBJET_YIELD.get(material, 1.0)
            fixed_multiplier = 2.0

        effective_cost_per_unit = (
            base_cost * conversion_factor *
            yield_factor * fixed_multiplier
        )

        return [
            material, machine, unit, base_cost, conversion_factor,
            yield_factor, fixed_multiplier, effective_cost_per_unit
        ]

    # Code
    now = pd.Timestamp.now(tz=LOCAL_TZ).strftime('%Y-%m-%d %H:%M')
    requests_df = load_sharepoint_export(REQUESTS, DATA_DIR)
    costs_df = load_sharepoint_export(COSTS, DATA_DIR)
    volumes_df = load_sharepoint_export(VOLUMES, DATA_DIR)

    # Clean requests_df
    requests_df['Direct Job?'] = requests_df['Direct Job?'].replace(
        'Indirect (overhead)', 'Indirect'
    )
    requests_df['Days to Complete'] = requests_df.apply(_business_days, axis=1).astype(
        'Int64'
    )
    requests_df['UpdateTime'] = now

    requests_df['Created'] = pd.to_datetime(requests_df['Created'])
    requests_df['Legacy Created time'] = pd.to_datetime(requests_df['Legacy Created time'])
    requests_df['Created_Corrected'] = requests_df['Created'].where(
        requests_df['Created'] != pd.Timestamp('2025-01-31'),
        requests_df['Legacy Created time'],
    )
    requests_df['Created_Corrected - Year'] = requests_df['Created_Corrected'].dt.to_period('Y').dt.to_timestamp()
    requests_df['Created_Corrected - Month'] = requests_df['Created_Corrected'].dt.to_period('M').dt.to_timestamp()

    requests_df['Start Date Sans Approval DT'] = (
        requests_df['Approved/In Queue D&T']
        .combine_first(requests_df['Printing D&T'])
        .combine_first(requests_df['Complete D&T'])
    )

    requests_df['Time to Approval'] = requests_df.apply(
        lambda row: (
            pd.NA
            if pd.isna(row['Created_Corrected'])
            or pd.isna(row['Start Date Sans Approval DT'])
            else int(
                np.busday_count(
                    np.datetime64(pd.Timestamp(row['Created_Corrected']).date(), 'D'),
                    np.datetime64(
                        pd.Timestamp(row['Start Date Sans Approval DT']).date(), 'D'
                    ),
                )
            )
            if np.datetime64(pd.Timestamp(row['Start Date Sans Approval DT']).date(), 'D')
            >= np.datetime64(pd.Timestamp(row['Created_Corrected']).date(), 'D')
            else pd.NA
        ),
        axis=1,
    )

    mask_missing = (
        requests_df['Complete D&T'].isna() | requests_df['Estimated Completion Date'].isna()
    )
    on_time = requests_df['Complete D&T'] <= requests_df['Estimated Completion Date']
    requests_df['Completed On Time'] = on_time.map({True: 'Yes', False: 'No'})

    requests_df.loc[mask_missing, 'Completed On Time'] = None

    cols = costs_df.columns[:-6]  # exclude last columns like ID, Created, etc.
    row = costs_df.iloc[0]
    row = pd.to_numeric(row, errors='coerce')

    parsed_cols = [parse_col(col, row) for col in cols]

    requests_costs_df = pd.DataFrame(
        parsed_cols,
        columns=[
            'material', 'machine', 'unit', 'base_cost', 'conversion_factor',
            'yield_factor', 'fixed_multiplier', 'effective_cost_per_unit'
        ],
        index=cols).reset_index(drop=True)

    requests_costs_df['unit'] = requests_costs_df['unit'].replace('CI', 'cu-in')
    requests_costs_df['material'] = requests_costs_df['material'].replace('F450', 'F450mc')
    requests_costs_df = requests_costs_df.sort_values(['material', 'machine'], ascending=True).reset_index(drop=True)
    requests_costs_df['material'] = requests_costs_df['material'].str.replace('Build sheet', 'Build Sheet', case=False, regex=True)

    # Clean volumes_df
    volumes_df = volumes_df.iloc[:, :-5]
    volumes_df = volumes_df.melt(var_name='machine', value_name='volume')

    # Write to SQL
    with pyro_engine.connect() as conn:
        if not conn.dialect.has_schema(conn, 'printing'):
            conn.execute(CreateSchema('printing'))
        conn.commit()

    costs_df.to_sql(
    name='material_cost', con=pyro_engine, schema='printing',
    if_exists='replace', index=False
    )
    requests_df.to_sql(
        name='request', con=pyro_engine, schema='printing',
        if_exists='replace', index=False
    )
    requests_costs_df.to_sql(
        name='request_cost', con=pyro_engine, schema='printing',
        if_exists='replace', index=False
    )
    volumes_df.to_sql(
        name='build_volume',
        con=pyro_engine,
        schema='printing',
        if_exists='replace',
        index=False,
    )

if __name__ == '__main__':
    main()
