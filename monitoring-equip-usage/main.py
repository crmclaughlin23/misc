"""Runs the equipment usage pipeline: historical runs/parts/uptime data, the live
current-equipment-status snapshot, or both."""

import argparse

import pandas as pd
from shared_config.sqlserver import PROD_SERVER, PYRO_DATABASE, PYRO_SERVER
from shared_utils.sqlserver import get_engine, read_table, replace_table

from equip_usage import config
from equip_usage.current_status import (
    build_current_equip_status,
    build_sorting_table,
    fetch_current_status_data,
    latest_avg_duration,
)
from equip_usage.historical import (
    build_parts_data,
    build_runs_data,
    build_uptime_data,
    fetch_historical_data,
)


def load_equip_pcs(info_engine) -> pd.DataFrame:
    equip_pcs = read_table(info_engine, config.EQUIP_PCS_QUERY)
    return equip_pcs[equip_pcs['PC'].str.contains('-A')]


def run_historical(info_engine, equip_pcs: pd.DataFrame) -> pd.DataFrame:
    """Build and write runs_data, parts_data, and uptime_data. Returns runs_data."""
    print('Fetching historical Runs/RealtimeData/Parts...')
    runs_df, realtime_df, parts_df = fetch_historical_data(PYRO_SERVER)

    parts_data, part_counts = build_parts_data(parts_df, realtime_df)
    runs_data = build_runs_data(runs_df, realtime_df, equip_pcs, part_counts)
    uptime_data = build_uptime_data(runs_data)

    print('Writing historical tables...')
    replace_table(runs_data, table_name='EquipUsage_Runs', engine_name=info_engine)
    replace_table(parts_data, table_name='EquipUsage_Parts', engine_name=info_engine)
    replace_table(uptime_data, table_name='EquipUsage_Uptime', engine_name=info_engine)

    return runs_data


def run_current_status(info_engine, equip_pcs: pd.DataFrame, runs_data: pd.DataFrame | None = None) -> None:
    """Build and write current_equip_status and sorting_table.

    If runs_data isn't supplied (standalone mode), Avg_Duration is read back
    from the EquipUsage_Runs table written by a prior historical run.
    """
    if runs_data is None:
        print('Reading EquipUsage_Runs for Avg_Duration lookup...')
        runs_data = read_table(info_engine, 'SELECT * FROM [EquipUsage_Runs]')

    print('Fetching current equipment status...')
    raw_status = fetch_current_status_data(PYRO_SERVER)
    avg_duration_lookup = latest_avg_duration(runs_data)

    current_equip_status = build_current_equip_status(raw_status, equip_pcs, avg_duration_lookup)
    sorting_table = build_sorting_table(current_equip_status)

    print('Writing current-status tables...')
    replace_table(current_equip_status, table_name='EquipUsage_Live', engine_name=info_engine)
    replace_table(sorting_table, table_name='EquipUsage_Sorting', engine_name=info_engine)


def main():
    parser = argparse.ArgumentParser(
        description=(
            'Build equipment usage tables: historical (runs/parts/uptime) and/or '
            'the live current-status snapshot.'
        )
    )
    parser.add_argument(
        '--mode',
        choices=['all', 'historical', 'current-status'],
        default='all',
        help=(
            "'historical' builds runs_data/parts_data/uptime_data. "
            "'current-status' builds the live snapshot + sorting table, reading "
            "Avg_Duration from the existing EquipUsage_Runs table. "
            "'all' runs both, using the freshly-built runs_data directly for "
            "Avg_Duration instead of re-reading it from SQL. Default: all."
        ),
    )
    args = parser.parse_args()

    info_engine = get_engine(PROD_SERVER, PYRO_DATABASE)
    equip_pcs = load_equip_pcs(info_engine)

    runs_data = None
    if args.mode in ('all', 'historical'):
        runs_data = run_historical(info_engine, equip_pcs)

    if args.mode in ('all', 'current-status'):
        run_current_status(info_engine, equip_pcs, runs_data=runs_data)

    print('\nDone.')


if __name__ == '__main__':
    main()
