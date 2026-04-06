from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import quote_plus

from sqlalchemy import create_engine


def _default_odbc() -> str:
    return (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=EDEQ-PS02;"
        "DATABASE=SUB_DISTRIBUCION;"
        "UID=usr-mtto;"
        "PWD=kC86r1BvZ2bVYGd9ikNf;"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )


@lru_cache(maxsize=1)
def get_engine():
    raw = os.getenv("SQLSERVER_ODBC", _default_odbc())
    return create_engine(f"mssql+pyodbc:///?odbc_connect={quote_plus(raw)}")
