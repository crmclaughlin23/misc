"""Historical equipment usage: runs_data, parts_data, and uptime_data.

Independent of current_status.py -- these build off full Runs/RealtimeData/Parts
history pulled from every CPC_* database, not the live snapshot.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
from shared_utils.sqlserver import get_engine

from . import config
from .database import column_exists, get_cpc_databases


def _query_one_db(pyro_server: str, db_name: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch raw Runs, RealtimeData summary, and Parts for one CPC database."""
    engine = get_engine(pyro_server, db_name)
    with engine.connect() as conn:
        runs_df = pd.read_sql(config.RUNS_QUERY, conn)

        purge_exists = column_exists(conn, 'RealtimeData', 'PurgeStatus')
        purge_column = (
            ', SUM(CASE WHEN PurgeStatus = -1 THEN 1 ELSE 0 END) AS PurgeTime'
            if purge_exists
            else ''
        )
        where_condition = 'WHERE RunStatus = -1' + (
            ' OR PurgeStatus = -1' if purge_exists else ''
        )
        realtime_query = config.REALTIME_SUMMARY_QUERY.format(
            purge_column=purge_column, where_condition=where_condition
        )
        realtime_df = pd.read_sql(realtime_query, conn)

        parts_df = pd.read_sql(config.PARTS_QUERY, conn)

    return runs_df, realtime_df, parts_df


def fetch_historical_data(pyro_server: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Pull Runs, RealtimeData summary, and Parts from every CPC_* database, in parallel."""
    databases = get_cpc_databases(pyro_server)

    runs_dfs, realtime_dfs, parts_dfs = [], [], []
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_query_one_db, pyro_server, db): db for db in databases
        }
        for future in as_completed(futures):
            db_name = futures[future]
            try:
                runs_df, realtime_df, parts_df = future.result()
                if not runs_df.empty:
                    runs_dfs.append(runs_df)
                if not realtime_df.empty:
                    realtime_dfs.append(realtime_df)
                if not parts_df.empty:
                    parts_dfs.append(parts_df)
                print(f'Loaded {db_name}')
            except Exception as e:
                print(f'Failed to load {db_name}: {e}')

    runs_df = (
        pd.concat(runs_dfs, ignore_index=True).drop_duplicates(
            subset=['Datafile'], keep='first'
        )
        if runs_dfs
        else pd.DataFrame()
    )
    realtime_df = pd.concat(realtime_dfs, ignore_index=True) if realtime_dfs else pd.DataFrame()
    parts_df = pd.concat(parts_dfs, ignore_index=True) if parts_dfs else pd.DataFrame()

    return runs_df, realtime_df, parts_df


def build_parts_data(
    parts_df: pd.DataFrame, realtime_df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Clean raw Parts data and compute per-run PartCount.

    Returns (parts_data, part_counts):
      - parts_data: per-part detail rows for the EquipUsage_Parts table.
      - part_counts: one row per Datafile with PartCount, for merging into runs_data.
    """
    df = pd.merge(parts_df, realtime_df, on='Datafile')

    df['Datafile'] = df['Datafile'].str.replace('.DAT', '', regex=False)
    df['Recipe'] = df['Recipe'].str.split('\\').str[-1]
    df['Date'] = df['StartTime'].dt.date

    counts = (
        df.groupby(['RunID', 'Datafile'])
        .agg(
            total_parts=('PartIndex', 'count'),
            non_zero_unique_parents=('ParentPartIndex', lambda x: x[x != 0].nunique()),
        )
        .reset_index()
    )
    counts['PartCount'] = counts['total_parts'] - counts['non_zero_unique_parents']
    part_counts = counts.drop_duplicates(subset=['Datafile'], keep='first')[
        ['Datafile', 'PartCount']
    ]

    parts_data = df[
        [
            'Equipment',
            'Date',
            'Datafile',
            'Program',
            'Recipe',
            'PartNumber',
            'PartName',
            'SerialNumber',
        ]
    ]

    return parts_data, part_counts


def build_runs_data(
    runs_df: pd.DataFrame,
    realtime_df: pd.DataFrame,
    equip_pcs: pd.DataFrame,
    part_counts: pd.DataFrame,
) -> pd.DataFrame:
    """Clean and enrich raw Runs data into the final runs_data table."""
    df = pd.merge(runs_df, equip_pcs, left_on='Equipment', right_on='Equip', how='left')
    df = pd.merge(df, realtime_df, on='Datafile')

    df['Date'] = df['StartTime'].dt.date
    df['PurgeTime'] = df['PurgeTime'].fillna(0)
    df['Recipe'] = df['Recipe_x']
    df['Equipment'] = df['Alt_Name']
    df['Datafile'] = df['Datafile'].str.replace('.DAT', '', regex=False)
    df['Duration'] = df['Duration'].round(1)
    df['Avg_Duration'] = (
        df.groupby(['Equipment', 'Recipe', 'RecipeRevision'])['Duration']
        .transform('median')
        .round(1)
    )
    df['Recipe'] = df['Recipe'].str.split('\\').str[-1]
    df['PurgeEndTime'] = df['EndTime'] + pd.to_timedelta(df['PurgeTime'], unit='m')

    df['next_StartTime'] = df['StartTime'].shift(-1)
    df['CureToCure'] = ((df['next_StartTime'] - df['EndTime']).dt.total_seconds() / 60).round(1)
    df['DoorToDoor'] = (
        (df['next_StartTime'] - df['PurgeEndTime']).dt.total_seconds() / 60
    ).round(1)

    df['Aborted'] = np.where(
        (df['Duration'] < (df['Avg_Duration'] * 0.5)) & (df['Duration'] > 5),
        'Yes',
        'No',
    )

    df = pd.merge(df, part_counts, on='Datafile', how='left')
    df['RunID'] = df['RunID_x']

    final_columns = [
        'RunID', 'Datafile', 'Equipment', 'Site', 'Recipe', 'RecipeRevision', 'Program',
        'Date', 'StartTime', 'EndTime', 'Duration', 'Avg_Duration', 'Operator',
        'Max_Air', 'Max_Part', 'Max_Seg', 'PurgeTime', 'PurgeEndTime', 'Aborted',
        'DoorToDoor', 'CureToCure', 'PartCount',
    ]
    df = df[final_columns]

    return df.drop_duplicates(subset=['Datafile'], keep='first')


def build_uptime_data(runs_data: pd.DataFrame) -> pd.DataFrame:
    """Expand each run into per-day uptime/downtime minutes, filling gaps between cures."""
    results = []

    uptime_analysis = runs_data[
        [
            'Datafile', 'Equipment', 'Site', 'Recipe', 'Program', 'StartTime',
            'EndTime', 'Duration', 'PurgeTime', 'PurgeEndTime',
        ]
    ].copy()
    uptime_analysis['Duration+Purge'] = (
        uptime_analysis['Duration'] + uptime_analysis['PurgeTime']
    )

    for _, row in uptime_analysis.iterrows():
        site = row['Site']
        equipment = row['Equipment']
        start_time = row['StartTime']
        end_time = row['EndTime']

        if start_time.date() == end_time.date():
            real_uptime = row['Duration']
            real_downtime = config.MINUTES_IN_DAY - real_uptime
            results.append(
                {
                    'Site': site, 'Equipment': equipment, 'Date': start_time.date(),
                    'RealUptime': real_uptime, 'RealDowntime': real_downtime,
                }
            )
        else:
            end_of_day = start_time.replace(hour=23, minute=59, second=59)
            minutes_first_day = (end_of_day - start_time).total_seconds() / 60
            minutes_second_day = (
                end_time - end_time.replace(hour=0, minute=0)
            ).total_seconds() / 60
            full_days = (end_time.date() - start_time.date()).days - 1

            results.append(
                {
                    'Site': site, 'Equipment': equipment, 'Date': start_time.date(),
                    'RealUptime': minutes_first_day,
                    'RealDowntime': config.MINUTES_IN_DAY - minutes_first_day,
                }
            )
            results.append(
                {
                    'Site': site, 'Equipment': equipment, 'Date': end_time.date(),
                    'RealUptime': minutes_second_day,
                    'RealDowntime': config.MINUTES_IN_DAY - minutes_second_day,
                }
            )
            for day in range(1, full_days + 1):
                full_day_date = (start_time + pd.Timedelta(days=day)).date()
                results.append(
                    {
                        'Site': site, 'Equipment': equipment, 'Date': full_day_date,
                        'RealUptime': config.MINUTES_IN_DAY, 'RealDowntime': 0,
                    }
                )

    # Fill full idle days between consecutive cures on the same equipment.
    # NOTE: ported as-is from the notebook -- 'site' here is whatever value it held
    # at the end of the loop above (i.e. the Site of the LAST run overall), not the
    # Site of uptime_analysis.iloc[i]. Pre-existing bug carried over from the
    # notebook; flagging rather than silently fixing since it changes output.
    for i in range(len(uptime_analysis) - 1):
        current_end_time = uptime_analysis.iloc[i]['EndTime']
        next_start_time = uptime_analysis.iloc[i + 1]['StartTime']

        if (next_start_time - current_end_time).days > 1:
            gap_days = (next_start_time.date() - current_end_time.date()).days - 1
            for day in range(gap_days):
                gap_day_date = (current_end_time + pd.Timedelta(days=day + 1)).date()
                results.append(
                    {
                        'Site': site,
                        'Equipment': uptime_analysis.iloc[i]['Equipment'],
                        'Date': gap_day_date,
                        'RealUptime': 0,
                        'RealDowntime': config.MINUTES_IN_DAY,
                    }
                )

    results_df = pd.DataFrame(results)

    summary = (
        results_df.groupby(['Site', 'Equipment', 'Date']).agg({'RealUptime': 'sum'}).reset_index()
    )
    summary['RealDowntime'] = config.MINUTES_IN_DAY - summary['RealUptime']

    summary['AdjustedUptime'] = (summary['RealUptime'] + config.UPTIME_ADJUSTMENT).clip(
        upper=config.MINUTES_IN_DAY
    )
    summary['AdjustedDowntime'] = config.MINUTES_IN_DAY - summary['AdjustedUptime']

    for col in ['RealUptime', 'RealDowntime', 'AdjustedUptime', 'AdjustedDowntime']:
        summary[col] = summary[col].astype(int)

    summary['Date'] = pd.to_datetime(summary['Date'])

    return summary
