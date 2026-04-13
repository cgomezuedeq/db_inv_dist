from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import excel_store
from db import get_engine
from excel_store import MONTHS_ES, build_report, build_series, load_sources_from_db, sanitize_dataframe_for_sql

MIN_DATA_YEAR = 2024


def _current_year() -> int:
    return datetime.now().year


def _validate_year(year: int) -> int:
    cy = _current_year()
    if year < MIN_DATA_YEAR or year > cy:
        raise HTTPException(
            status_code=400,
            detail=f"El año debe estar entre {MIN_DATA_YEAR} y {cy}.",
        )
    return year


def _excel_bytes_to_sql(contents: bytes, year: int) -> list[str]:
    bio = BytesIO(contents)
    xl = pd.ExcelFile(bio)
    for sheet in ("PPTO", "EJE"):
        if sheet not in xl.sheet_names:
            raise ValueError(f"El archivo debe incluir la hoja «{sheet}».")

    engine = get_engine()
    tables: list[str] = []
    for sheet in ("PPTO", "EJE"):
        bio.seek(0)
        df = pd.read_excel(bio, sheet_name=sheet)
        df = sanitize_dataframe_for_sql(df)
        table = f"sd_inv_{year}_{sheet}"
        df.to_sql(table, con=engine, if_exists="replace", index=False, schema="dbo")
        tables.append(f"dbo.{table}")
    return tables


app = FastAPI(title="Dashboard Inversiones API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health():
    y = _current_year()
    return {
        "ok": True,
        "dataSource": "sql",
        "tablesPattern": "dbo.sd_inv_{año}_{EJE|PPTO}",
        "defaultYear": y,
        "yearRange": {"min": MIN_DATA_YEAR, "max": y},
    }


@app.get("/api/v1/months")
def months():
    return [{"key": k, "label": lbl} for (k, lbl) in MONTHS_ES]


@app.get("/api/v1/report")
def report(
    month: str = Query(default="Dic", description="Mes: Ene, Feb, Mar, ... Dic"),
    year: int | None = Query(default=None, description=f"Año ({MIN_DATA_YEAR} … año en curso); por defecto año actual"),
):
    y = _validate_year(year if year is not None else _current_year())
    try:
        eje_df, ppto_df = load_sources_from_db(get_engine(), y)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return build_report(eje_df, ppto_df, month)


@app.get("/api/v1/series")
def series(
    id: int = Query(..., description="id de item (report.items[].id)"),
    year: int | None = Query(default=None, description="Año de las tablas dbo.sd_inv_{año}_*"),
):
    y = _validate_year(year if year is not None else _current_year())
    try:
        eje_df, ppto_df = load_sources_from_db(get_engine(), y)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        return build_series(eje_df, ppto_df, id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/upload")
async def upload_excel_to_db(
    year: int = Form(..., description="Año para nombres de tabla dbo.sd_inv_{año}_{hoja}"),
    file: UploadFile = File(...),
):
    _validate_year(year)

    if not file.filename or not str(file.filename).lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Se requiere un archivo .xlsx o .xlsm")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Archivo vacío")

    try:
        tables = _excel_bytes_to_sql(contents, year)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo escribir en SQL Server: {exc}") from exc

    return {"ok": True, "year": year, "tables": tables}


@app.get("/api/v1/debug")
def debug():
    y = _current_year()
    try:
        sample = build_report(*load_sources_from_db(get_engine(), y), "Mar")
        return {
            "excel_store_file": getattr(excel_store, "__file__", None),
            "year": y,
            "build_report_keys": list(sample.keys()),
            "totales_keys": list(sample["totales"].keys()),
            "item_keys": list(sample["items"][0].keys()) if sample.get("items") else [],
        }
    except Exception as exc:
        return {"error": str(exc), "year": y}
