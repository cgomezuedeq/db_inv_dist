from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import excel_store
from db import get_engine
from excel_store import MONTHS_ES, build_report, build_series, load_sources


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_EJE = str((BASE_DIR.parent / "EJE.xlsx").resolve())
DEFAULT_PPTO = str((BASE_DIR.parent / "PPTO.xlsx").resolve())


def _sources() -> tuple[str, str]:
    eje = os.getenv("EJE_XLSX", DEFAULT_EJE)
    ppto = os.getenv("PPTO_XLSX", DEFAULT_PPTO)
    return eje, ppto


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
        table = f"sd_inv_{year}_{sheet}"
        df.to_sql(table, con=engine, if_exists="replace", index=False, schema="dbo")
        tables.append(table)
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
    eje, ppto = _sources()
    return {"ok": True, "eje": eje, "ppto": ppto}


@app.get("/api/v1/months")
def months():
    return [{"key": k, "label": lbl} for (k, lbl) in MONTHS_ES]


@app.get("/api/v1/report")
def report(month: str = Query(default="Mar", description="Mes: Ene, Feb, Mar, ... Dic")):
    eje_path, ppto_path = _sources()
    eje_df, ppto_df = load_sources(eje_path, ppto_path)
    return build_report(eje_df, ppto_df, month)


@app.get("/api/v1/series")
def series(id: int = Query(..., description="id de item (report.items[].id)")):
    eje_path, ppto_path = _sources()
    eje_df, ppto_df = load_sources(eje_path, ppto_path)
    return build_series(eje_df, ppto_df, id)


@app.post("/api/v1/upload")
async def upload_excel_to_db(
    year: int = Form(..., description="Año para nombres de tabla dbo.sd_inv_{año}_{hoja}"),
    file: UploadFile = File(...),
):
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
    return {
        "excel_store_file": getattr(excel_store, "__file__", None),
        "build_report_keys": list(build_report(*load_sources(*_sources()), "Mar").keys()),
        "totales_keys": list(build_report(*load_sources(*_sources()), "Mar")["totales"].keys()),
        "item_keys": list(build_report(*load_sources(*_sources()), "Mar")["items"][0].keys()),
    }

