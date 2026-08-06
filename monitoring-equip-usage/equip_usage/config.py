"""Configuration constants and SQL query templates for the equipment usage pipeline."""

MINUTES_IN_DAY = 1440
UPTIME_ADJUSTMENT = 216

# CPC_* database discovery, run against the pyrometry server's master DB
CPC_DATABASE_QUERY = """
    SELECT name
    FROM sys.databases
    WHERE name LIKE 'CPC_%'
        AND name NOT LIKE 'CPC_Staging'
"""

# Equipment/site lookup and alt-name mapping table
EQUIP_PCS_QUERY = 'SELECT * FROM [Equipment PCs]'

# --- Historical (runs / parts / uptime) queries ---------------------------

RUNS_QUERY = 'SELECT * FROM dbo.Runs ORDER BY StartTime'

# {purge_column} and {where_condition} are filled in per-database depending on
# whether that CPC database's RealtimeData table has a PurgeStatus column.
REALTIME_SUMMARY_QUERY = """
    SELECT Datafile,
        MIN(CASE WHEN SEG >= 2 THEN Program END) AS Program,
        MIN(Recipe) AS Recipe,
        MAX(ROUND(RunTime, 1)) AS RunTime,
        MAX(ROUND(TSet_Air, 1)) AS Max_Air,
        MAX(ROUND(TSet_Part, 1)) AS Max_Part,
        CAST(MAX(SEG) AS INT) AS Max_Seg
        {purge_column}
    FROM dbo.RealtimeData
    {where_condition}
    GROUP BY Datafile
"""

PARTS_QUERY = """
    SELECT
        r.RunID,
        r.Equipment,
        r.Datafile,
        r.StartTime,
        p.PartIndex,
        p.ParentPartIndex,
        p.PartNumber,
        p.PartName,
        p.SerialNumber
    FROM dbo.Runs r
    INNER JOIN dbo.Parts p ON r.RunID = p.RunID
"""

# --- Current-status (live snapshot) query ----------------------------------

# {press_column}, {press_set_column}, and {purge_case} depend on whether that
# CPC database's RealtimeData table has Press and PurgeStatus columns.
CURRENT_STATUS_QUERY = """
    SELECT TOP (1)
        DataTime AS Time,
        Datafile,
        Program,
        Recipe,
        ROUND(RunTime, 1) AS RunTime,
        ROUND(AirTC, 1) AS AirTC,
        ROUND(TSet_Air, 1) AS AirSet,
        {press_column},
        {press_set_column},
        ROUND(HITC, 1) AS HiTC,
        ROUND(LoTC, 1) AS LoTC,
        ROUND(TSet_Part, 1) AS PartSet,
        CASE
            WHEN RunStatus = -1 THEN 'Running'
            WHEN AbortStatus = -1 THEN 'Aborting'
            {purge_case}
            ELSE 'Idle'
        END AS RunStatus,
        SEG AS Seg,
        ROUND(SegTime, 1) AS SegTime,
        ROUND(SegTimeLeft, 1) AS SegTimeLeft
    FROM dbo.RealtimeData
    ORDER BY DataTime DESC
"""
