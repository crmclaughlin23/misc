"""Shared per-database helpers used by both the historical and current-status builds."""

from sqlalchemy import text
from sqlalchemy.engine import Connection

from shared_utils.sqlserver import get_engine, list_databases

from . import config


def get_cpc_databases(pyro_server: str) -> list[str]:
    """Return the list of CPC_* database names on the pyrometry server."""
    master_engine = get_engine(pyro_server, 'master')
    return list_databases(master_engine, config.CPC_DATABASE_QUERY)


def column_exists(conn: Connection, table: str, column: str) -> bool:
    """Check whether a column exists on a table, using an already-open connection."""
    result = conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = :table AND COLUMN_NAME = :column
            """
        ),
        {'table': table, 'column': column},
    )
    return result.fetchone()[0] > 0
