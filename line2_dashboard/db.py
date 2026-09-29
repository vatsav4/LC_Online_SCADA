"""SQL Server access for the Line 2 dashboard."""
from . import config


def connect():
    """Open a connection to the Line 2 SQL Server (non-default port, e.g. 49561)."""
    if config.DB_BACKEND == "pymssql":
        import pymssql

        return pymssql.connect(
            server=config.DB_HOST,
            port=str(config.DB_PORT),
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME,
            login_timeout=config.DB_LOGIN_TIMEOUT,
            timeout=30,
        )

    import pyodbc

    # SQL Server takes the port after a comma, not a colon: SERVER=host,49561
    conn_str = (
        f"DRIVER={{{config.DB_ODBC_DRIVER}}};"
        f"SERVER={config.DB_HOST},{config.DB_PORT};"
        f"DATABASE={config.DB_NAME};"
        f"UID={config.DB_USER};PWD={config.DB_PASSWORD};"
        f"Encrypt={'yes' if config.DB_ENCRYPT else 'no'};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=config.DB_LOGIN_TIMEOUT)


def _placeholder():
    return "%s" if config.DB_BACKEND == "pymssql" else "?"


def _query(sql, params=()):
    conn = connect()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def _log_filters(alias):
    """Extra WHERE/ON conditions for the log table plus their parameters."""
    conditions, params = [], []
    if config.SHOP_ID is not None:
        conditions.append(f"{alias}.shop_id_id = {_placeholder()}")
        params.append(config.SHOP_ID)
    if config.LOOKBACK_HOURS > 0:
        conditions.append(
            f"{alias}.in_date_time >= DATEADD(HOUR, -{int(config.LOOKBACK_HOURS)}, GETDATE())"
        )
    return conditions, params


def fetch_station_rows():
    """Every station with its current vehicle, joined to that vehicle's log rows (newest first).

    Stations with no log rows yet come back once with NULL log columns.
    `=` on varchar ignores trailing spaces in SQL Server, so padded mat_no values still match.
    """
    if config.DEMO_MODE:
        from . import demo

        return demo.station_rows()

    conditions, params = _log_filters("l")
    extra_on = "".join(f" AND {c}" for c in conditions)
    sql = f"""
        SELECT m.StationNumber, m.VC_Number, m.MAT_Number,
               l.id, l.in_date_time, l.mat_no, l.type_data, l.data
        FROM {config.MAPPING_TABLE} AS m
        LEFT JOIN {config.LOG_TABLE} AS l
               ON l.mat_no = m.MAT_Number{extra_on}
        ORDER BY m.StationNumber, l.in_date_time DESC, l.id DESC
    """
    return _query(sql, params)


def fetch_recent_events(limit):
    """Latest log rows across the whole line, for the live event feed."""
    if config.DEMO_MODE:
        from . import demo

        return demo.recent_events(limit)

    conditions, params = _log_filters("l")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT TOP ({int(limit)}) l.id, l.in_date_time, l.mat_no, l.type_data, l.data
        FROM {config.LOG_TABLE} AS l
        {where}
        ORDER BY l.in_date_time DESC, l.id DESC
    """
    return _query(sql, params)


def ping():
    if config.DEMO_MODE:
        return True
    _query("SELECT 1 AS ok")
    return True
