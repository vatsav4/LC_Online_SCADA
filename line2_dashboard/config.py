"""Configuration for the Line 2 dashboard, read from environment / .env file."""
import os
import re
from pathlib import Path

_ENV_FILE = Path(__file__).with_name(".env")


def _load_env_file():
    """Minimal .env loader so python-dotenv is not a hard dependency."""
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def _bool(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    return int(os.getenv(name, default))


_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


def _table(name, default):
    """Table names are interpolated into SQL, so only allow db.schema.table identifiers."""
    parts = os.getenv(name, default).split(".")
    if not 1 <= len(parts) <= 3 or not all(_IDENT.match(p) for p in parts):
        raise ValueError(f"{name} must look like Database.schema.Table")
    return ".".join(f"[{p}]" for p in parts)


LINE_NAME = os.getenv("LINE_NAME", "Line 2")

# SQL Server: this line's server only listens on the non-default port 49561.
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = _int("DB_PORT", 49561)
DB_NAME = os.getenv("DB_NAME", "Industry4_157")
DB_USER = os.getenv("DB_USER", "sa")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_BACKEND = os.getenv("DB_BACKEND", "pyodbc").lower()  # "pyodbc" or "pymssql"
DB_ODBC_DRIVER = os.getenv("DB_ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
DB_ENCRYPT = _bool("DB_ENCRYPT", False)
DB_LOGIN_TIMEOUT = _int("DB_LOGIN_TIMEOUT", 5)

MAPPING_TABLE = _table("MAPPING_TABLE", "dbo.Station_Mapping")
LOG_TABLE = _table("LOG_TABLE", "dbo.smartapp_linedata_line_log_dump")

# Optional filter if the log table holds data for more than one shop/line.
SHOP_ID = os.getenv("SHOP_ID", "").strip() or None
# Only consider log rows newer than this many hours (0 = no limit).
LOOKBACK_HOURS = _int("LOOKBACK_HOURS", 0)
# Only show a log row on a station card if its "Station No" matches that station.
STRICT_STATION_MATCH = _bool("STRICT_STATION_MATCH", True)

EVENTS_LIMIT = _int("EVENTS_LIMIT", 50)
REFRESH_SECONDS = _int("REFRESH_SECONDS", 5)

DEMO_MODE = _bool("DEMO_MODE", False)

HOST = os.getenv("HOST", "0.0.0.0")
PORT = _int("PORT", 5002)
