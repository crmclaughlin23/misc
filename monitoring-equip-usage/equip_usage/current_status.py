"""Live equipment status: current_equip_status and sorting_table.

Can run standalone -- Avg_Duration (needed for the TimeLeft calc) is pulled from
a runs_data DataFrame that the caller supplies, either freshly built by
historical.py or read back from the EquipUsage_Runs SQL table.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
from shared_utils.sqlserver import get_engine

from . import config
from .database import column_exists, get_cpc_databases


def _query_one_db(pyro_server: str, db_name: str) -> pd.DataFrame:
    """Fetch the latest RealtimeData snapshot for one CPC database."""
    engine = get_engine(pyro_server, db_name)
    with engine.connect() as conn:
        press_exists = column_exists(conn, 'RealtimeData', 'Press')
        purge_exists = column_exists(conn, 'RealtimeData', 'PurgeStatus')

        query = config.CURRENT_STATUS_QUERY.format(
            press_column='ROUND(Press, 1) AS Press' if press_exists else '0 AS Press',
            press_set_column=(
                'ROUND(PSet, 1) AS PressSet' if press_exists else '0 AS PressSet'
            ),
            purge_case="WHEN PurgeStatus = -1 THEN 'Purging'" if purge_exists else '',
        )
        return pd.read_sql(query, conn)


def fetch_current_status_data(pyro_server: str) -> pd.DataFrame:
    """Pull the latest per-equipment snapshot from every CPC_* database, in parallel."""
    databases = get_cpc_databases(pyro_server)

    dfs = []
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_query_one_db, pyro_server, db): db for db in databases
        }
        for future in as_completed(futures):
            db_name = futures[future]
            try:
                df = future.result()
                if not df.empty:
                    dfs.append(df)
                    print(f'Loaded {db_name}')
            except Exception as e:
                print(f'Failed to load {db_name}: {e}')

    if not dfs:
        return pd.DataFrame()

    combined = pd.concat(dfs, ignore_index=True)
    combined['Datafile'] = combined['Datafile'].str.replace('.DAT', '', regex=False)
    combined['Recipe'] = combined['Recipe'].str.split('\\').str[-1]
    return combined


def latest_avg_duration(runs_data: pd.DataFrame) -> pd.DataFrame:
    """Reduce runs_data to the most recent row per Equipment+Recipe, for the Avg_Duration lookup."""
    return runs_data.loc[runs_data.groupby(['Equipment', 'Recipe'])['StartTime'].idxmax()]


def build_current_equip_status(
    raw_status: pd.DataFrame,
    equip_pcs: pd.DataFrame,
    avg_duration_lookup: pd.DataFrame,
) -> pd.DataFrame:
    """
    Clean the raw per-equipment snapshot and attach TimeLeft.

    avg_duration_lookup must have one row per Equipment+Recipe with an
    Avg_Duration column -- see latest_avg_duration().
    """
    df = raw_status.copy()
    df['Equipment'] = df['Datafile'].str.split(r'[-_]').str[0]
    df = df.sort_values(by='Time', ascending=False).reset_index(drop=True)

    df = pd.merge(df, equip_pcs, left_on='Equipment', right_on='DAT_Name', how='left')
    df['Equipment'] = df['Alt_Name']

    df = df[
        [
            'Time', 'Equipment', 'Site', 'Datafile', 'Program', 'Recipe', 'RunTime',
            'RunStatus', 'AirTC', 'AirSet', 'Press', 'PressSet', 'HiTC', 'LoTC', 'PartSet',
        ]
    ]
    df = df.sort_values(by=['Site', 'Equipment']).reset_index(drop=True)

    df = pd.merge(
        df,
        avg_duration_lookup[['Equipment', 'Recipe', 'Avg_Duration']],
        on=['Equipment', 'Recipe'],
        how='left',
    )

    df['TimeLeft'] = (df['Avg_Duration'] - df['RunTime']).round(0).fillna(-99999).astype(int)
    df['TimeLeft'] = df['TimeLeft'].replace(-99999, 'FIRST RUN')
    df['TimeLeft'] = df['TimeLeft'].apply(
        lambda x: f'{x:,}' if isinstance(x, int) and x != 'FIRST RUN' else x
    )
    df['Avg_Duration'] = df['Avg_Duration'].fillna('FIRST RUN')

    return df


def build_sorting_table(current_equip_status: pd.DataFrame) -> pd.DataFrame:
    """Rank equipment by alphabetic prefix + numeric suffix for consistent display ordering."""

    def extract_parts(alt_name):
        alpha_part = ''.join(filter(str.isalpha, alt_name))
        num_part = ''.join(filter(str.isdigit, alt_name))
        return alpha_part, int(num_part) if num_part else np.nan

    sorting = current_equip_status.copy()
    sorting[['AlphaPart', 'NumPart']] = (
        sorting['Equipment'].apply(extract_parts).apply(pd.Series)
    )
    sorted_ = sorting.sort_values(by=['AlphaPart', 'NumPart']).reset_index(drop=True)
    sorted_['Sorting#'] = range(1, len(sorted_) + 1)

    sorting = sorting.merge(sorted_[['Equipment', 'Sorting#']], on='Equipment', how='left')
    sorting = sorting.drop(columns=['AlphaPart', 'NumPart'])
    sorting = sorting.sort_values(by='Sorting#')

    return sorting[['Equipment', 'Site', 'Sorting#']].reset_index(drop=True)
