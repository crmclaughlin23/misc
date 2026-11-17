"""DataFrame-in, DataFrame-out transforms. No file or SQL I/O."""

import re

import numpy as np
import pandas as pd

import config


# ---------------------------------------------------------------- helpers
def _busday_span(start, end):
    """Business days from start to end; NA if either is missing or end < start."""
    if pd.isna(start) or pd.isna(end):
        return pd.NA
    start = np.datetime64(pd.Timestamp(start).date(), 'D')
    end = np.datetime64(pd.Timestamp(end).date(), 'D')
    return int(np.busday_count(start, end)) if end >= start else pd.NA


def _days_to_complete(row, cutover):
    created, legacy = row['Created'], row['Legacy Created time']
    if pd.notna(created) and created > cutover:
        start = created
    elif pd.notna(legacy):
        start = legacy
    else:
        return pd.NA
    return _busday_span(start, row['Complete D&T'])


# ---------------------------------------------------------------- request (job grain)
def clean_requests(df, now):
    """One row per job, with derived dates and durations."""
    df = df.copy()
    migration = pd.Timestamp(config.MIGRATION_DATE)

    df['Direct Job?'] = df['Direct Job?'].replace('Indirect (overhead)', 'Indirect')
    df['Days to Complete'] = df.apply(_days_to_complete, axis=1, cutover=migration.date()).astype('Int64')
    df['UpdateTime'] = now

    df['Created'] = pd.to_datetime(df['Created'])
    df['Legacy Created time'] = pd.to_datetime(df['Legacy Created time'])
    df['Created_Corrected'] = df['Created'].where(df['Created'] != migration, df['Legacy Created time'])
    df['Created_Corrected - Year'] = df['Created_Corrected'].dt.to_period('Y').dt.to_timestamp()
    df['Created_Corrected - Month'] = df['Created_Corrected'].dt.to_period('M').dt.to_timestamp()

    df['Start Date Sans Approval DT'] = (
        df['Approved/In Queue D&T']
        .combine_first(df['Printing D&T'])
        .combine_first(df['Complete D&T'])
    )
    df['Time to Approval'] = [
        _busday_span(s, e) for s, e in zip(df['Created_Corrected'], df['Start Date Sans Approval DT'])
    ]

    on_time = (df['Complete D&T'] <= df['Estimated Completion Date']).map({True: 'Yes', False: 'No'})
    missing = df['Complete D&T'].isna() | df['Estimated Completion Date'].isna()
    df['Completed On Time'] = on_time.where(~missing, None)
    return df


# ---------------------------------------------------------------- child tables (ID + grain columns only)
def build_request_machine(df):
    """One row per (ID, Machine) from the Machine multi-choice string."""
    out = df[['ID', 'Machine', 'Build Time']].copy()
    out['Machine'] = out['Machine'].fillna('').str.split(r'[;,]')
    out = out.explode('Machine')
    out['Machine'] = out['Machine'].str.strip()
    n = out.groupby('ID')['Machine'].transform(lambda s: (s != '').sum())
    out['Machine Build Time'] = pd.to_numeric(out['Build Time'], errors='coerce') / n.where(n > 0)
    return out[['ID', 'Machine', 'Machine Build Time']].reset_index(drop=True)


def build_request_stage(df):
    """One row per (ID, stage) for completed jobs: start, end, days in stage."""
    stages = [c for c in config.STAGES if c in df]
    before_complete = [s for s in stages if s != 'Complete D&T']
    done = df[df['Status'] == 'Complete'].dropna(subset=before_complete, how='all')
    order = {s.removesuffix(' D&T'): i for i, s in enumerate(stages)}

    out = (
        done.melt(id_vars='ID', value_vars=stages, var_name='stage', value_name='start')
        .dropna(subset=['start'])
        .assign(start=lambda d: pd.to_datetime(d['start']),
                stage=lambda d: d['stage'].str.removesuffix(' D&T'))
    )
    out['order'] = out['stage'].map(order)
    out = out.sort_values(['ID', 'start', 'order'])
    out['end'] = out.groupby('ID')['start'].shift(-1)
    out['days'] = (out['end'] - out['start']).dt.days
    out = out[out['stage'] != 'Complete']
    return out[['ID', 'stage', 'order', 'start', 'end', 'days']].reset_index(drop=True)


def build_request_material(df):
    """One row per (ID, machine, tier, material) with a non-zero quantity."""
    parts = []
    for col in df.columns:
        m = re.match(r'^(.+?) Qty T([123])$', col)
        if not m or col.startswith(('Total', 'Print Failure')):
            continue
        stem, tier = m[1], m[2]
        mat_col, color_col = f'{stem} T{tier}', f'{stem} Color T{tier}'
        role = 'Support' if 'Support' in stem else 'Model'
        machine = (re.split(r' (?:Model|Support)', stem)[0]
                   if re.search(r' (Model|Support)', stem) else stem.split(' ')[0])
        material = df[mat_col] if mat_col in df else pd.Series(stem, index=df.index)
        if mat_col in df and color_col in df:  # color typed into the material field
            material = material.where(material != df[color_col], df[f'{stem} T1'])
        parts.append(pd.DataFrame({
            'ID': df['ID'],
            'Machine': machine,
            'Material': material.fillna('Unspecified'),
            'Role': role,
            'Qty': pd.to_numeric(df[col], errors='coerce'),
        }))
    out = pd.concat(parts, ignore_index=True)
    return out[out['Qty'].fillna(0) != 0].reset_index(drop=True)


def build_request_job_size(df, material):
    """One row per (ID, Machine): model + support qty per part and its size bin."""
    out = (material.groupby(['ID', 'Machine'], as_index=False)['Qty'].sum()
           .rename(columns={'Qty': 'Total Qty'}))
    parts = pd.to_numeric(out['ID'].map(df.set_index('ID')['Total Part Quantity']), errors='coerce')
    out['Avg Qty per Part'] = out['Total Qty'] / parts.where(parts > 0)
    bins = pd.cut(out['Avg Qty per Part'], config.SIZE_BINS, labels=config.SIZE_LABELS, right=False)
    out['Size Bin'] = bins.astype(str).replace('nan', None)
    out['Size Bin Order'] = bins.cat.codes + 1
    return out


# ---------------------------------------------------------------- costs and volumes
COST_COLUMNS = [
    'material', 'machine', 'unit', 'base_cost', 'conversion_factor',
    'yield_factor', 'fixed_multiplier', 'effective_cost_per_unit',
]


def _parse_cost_col(col, base_cost):
    """'Material, Machine, Unit' column name + base cost -> one request_cost row."""
    parts = [p.strip() for p in col.split(',')]
    if len(parts) != 3:
        return [None] * len(COST_COLUMNS)
    material, machine, unit = parts

    conversion, yield_factor, multiplier = 1.0, 1.0, 1.0
    if machine == 'Markforged Mk2':
        conversion = config.CC_TO_IN3
    elif machine == 'Objet350':
        conversion = config.IN3_TO_CC
        yield_factor = config.OBJET_YIELD.get(material, 1.0)
        multiplier = config.OBJET_FIXED_MULTIPLIER

    effective = base_cost * conversion * yield_factor * multiplier
    return [material, machine, unit, base_cost, conversion, yield_factor, multiplier, effective]


def build_request_cost(costs_df):
    """One row per (material, machine) with effective cost per unit."""
    cols = costs_df.columns[:-6]  # exclude trailing ID, Created, etc.
    row = pd.to_numeric(costs_df.iloc[0], errors='coerce')
    out = pd.DataFrame([_parse_cost_col(c, row[c]) for c in cols], columns=COST_COLUMNS)

    out['unit'] = out['unit'].replace('CI', 'cu-in')
    out['material'] = out['material'].replace('F450', 'F450mc')
    out = out.sort_values(['material', 'machine']).reset_index(drop=True)
    out['material'] = out['material'].str.replace('Build sheet', 'Build Sheet', case=False, regex=True)
    return out


def build_build_volume(volumes_df):
    """One row per machine with its build volume."""
    return volumes_df.iloc[:, :-5].melt(var_name='machine', value_name='volume')


# ---------------------------------------------------------------- all tables
def build_tables(requests, costs, volumes, now):
    """Return {table_name: DataFrame} for every table written to SQL."""
    requests = clean_requests(requests, now)
    material = build_request_material(requests)
    return {
        'request': requests,
        'request_machine': build_request_machine(requests),
        'request_stage': build_request_stage(requests),
        'request_material': material,
        'request_job_size': build_request_job_size(requests, material),
        'material_cost': costs,
        'request_cost': build_request_cost(costs),
        'build_volume': build_build_volume(volumes),
    }
