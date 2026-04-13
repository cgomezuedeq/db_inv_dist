from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import pandas as pd


MONTHS_ES = [
    ("Ene", "Enero"),
    ("Feb", "Febrero"),
    ("Mar", "Marzo"),
    ("Ab", "Abril"),
    ("May", "Mayo"),
    ("Jun", "Junio"),
    ("Jul", "Julio"),
    ("Ago", "Agosto"),
    ("Sep", "Septiembre"),
    ("Oct", "Octubre"),
    ("Nov", "Noviembre"),
    ("Dic", "Diciembre"),
]

# Corregir error histórico: en Excel el mes de abril suele ser «Ab».
_MONTH_HEADER_ALIASES: dict[str, str] = {
    "abr": "Ab",
    "ab": "Ab",
    "ago": "Ago",
}


def _normalize_month_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    for c in df.columns:
        k = str(c).strip()
        lk = k.lower()
        if lk in _MONTH_HEADER_ALIASES:
            target = _MONTH_HEADER_ALIASES[lk]
            if target in df.columns and target != k:
                continue
            rename[k] = target
    return df.rename(columns=rename) if rename else df


def _find_column(df: pd.DataFrame, *candidates: str) -> str | None:
    low = {str(c).strip().lower(): c for c in df.columns}
    for name in candidates:
        if name.lower() in low:
            return str(low[name.lower()])
    return None


def _normalize_ind_raw(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return "1" if raw else "0"
    if isinstance(raw, (int,)) and not isinstance(raw, bool):
        return str(int(raw))
    if isinstance(raw, float):
        if pd.isna(raw) or math.isnan(raw):
            return ""
        f = float(raw)
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
        s = ("%f" % f).rstrip("0").rstrip(".")
        return s
    s = str(raw).strip()
    return s


def _parent_ind(ind: str) -> str | None:
    if not ind or "." not in ind:
        return None
    parts = [p for p in ind.split(".") if p != ""]
    if len(parts) <= 1:
        return None
    return ".".join(parts[:-1])


def _nivel_from_ind(ind: str) -> int:
    if not ind:
        return 1
    parts = [p for p in ind.split(".") if p != ""]
    return max(1, len(parts))


def _detalle_cell_str(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, float) and pd.isna(raw):
        return ""
    return str(raw).strip()


def _resolve_ind_det_columns(df: pd.DataFrame) -> tuple[str | None, str | None]:
    """
    Localiza columnas de jerarquía y descripción.

    - Formato nuevo: ``IND``, ``DETALLE``.
    - Formato legacy (Excel sin encabezados): ``Unnamed: 0`` = códigos, ``Unnamed: 1`` = texto.
    """
    col_ind = _find_column(df, "IND", "ind")
    col_det = _find_column(df, "DETALLE", "Detalle", "detalle")

    cols = list(df.columns)
    if not col_ind:
        for name in ("Unnamed: 0",):
            if name in cols:
                col_ind = name
                break
        if not col_ind and cols:
            c0 = str(cols[0])
            if c0.startswith("Unnamed:") or c0.lower() == "ind":
                col_ind = cols[0]

    if not col_det:
        for name in ("Unnamed: 1",):
            if name in cols:
                col_det = name
                break
        if not col_det and len(cols) > 1:
            c1 = str(cols[1])
            if c1.startswith("Unnamed:") or c1.lower() in ("detalle", "concepto"):
                col_det = cols[1]

    return col_ind, col_det


def sanitize_dataframe_for_sql(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fuerza columnas de jerarquía y descripción como texto antes de ``to_sql``.
    Así códigos como 1.1 no quedan como ``float`` (1.1000000000000001) en SQL Server.
    """
    out = df.copy()
    col_ind, col_det = _resolve_ind_det_columns(out)
    if col_ind:
        out[col_ind] = out[col_ind].map(_normalize_ind_raw)
    if col_det:
        out[col_det] = out[col_det].map(_detalle_cell_str)
    return out


def month_matrix_from_dataframe(df: pd.DataFrame, source_label: str) -> pd.DataFrame:
    """
    Convierte un DataFrame crudo (Excel o filas SQL) al formato interno del reporte.
    """
    df = _normalize_month_columns(df.copy())

    col_ind, col_det = _resolve_ind_det_columns(df)

    if not col_ind or not col_det:
        raise ValueError(
            f"Se requieren columnas de jerarquía y descripción (IND/DETALLE o Unnamed: 0/Unnamed: 1) "
            f"en {source_label}. Columnas encontradas: {list(df.columns)}"
        )

    month_cols = [m for (m, _) in MONTHS_ES if m in df.columns]
    if not month_cols:
        raise ValueError(
            f"No se encontraron columnas de meses en {source_label}. "
            f"Se esperan claves como: Ene, Feb, …, Dic. Columnas: {list(df.columns)}"
        )

    out = df[[col_ind, col_det] + month_cols].copy()
    out = out.rename(columns={col_ind: "ind_raw", col_det: "detalle_raw"})

    out["ind"] = out["ind_raw"].map(_normalize_ind_raw)
    out["concepto"] = out["detalle_raw"].map(
        lambda x: str(x).strip() if x is not None and not (isinstance(x, float) and pd.isna(x)) else ""
    )
    out["indent"] = (out["ind"].map(_nivel_from_ind) - 1) * 4
    out["nivel"] = out["ind"].map(_nivel_from_ind)

    for m in month_cols:
        out[m] = pd.to_numeric(out[m], errors="coerce").fillna(0.0)

    return out


def _read_month_matrix(path: Path, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet_name)
    return month_matrix_from_dataframe(df, f"{path.name} «{sheet_name}»")


def load_sources_from_db(engine, year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Lee ``dbo.sd_inv_{año}_EJE`` y ``dbo.sd_inv_{año}_PPTO``.
    """
    eje = _read_month_matrix_from_db(engine, year, "EJE")
    ppto = _read_month_matrix_from_db(engine, year, "PPTO")
    return eje, ppto


def _read_month_matrix_from_db(engine, year: int, sheet: str) -> pd.DataFrame:
    if sheet not in ("EJE", "PPTO"):
        raise ValueError("La hoja debe ser EJE o PPTO.")
    table = f"sd_inv_{year}_{sheet}"
    from sqlalchemy import text

    q = text(f"SELECT * FROM [dbo].[{table}]")
    try:
        df = pd.read_sql(q, con=engine)
    except Exception as exc:
        raise ValueError(
            f"No se pudo leer dbo.{table}. Cargue un Excel para ese año o verifique permisos y conexión. "
            f"Detalle: {exc}"
        ) from exc
    if df.empty:
        raise ValueError(f"La tabla dbo.{table} no tiene filas. Cargue datos con «Cargar Excel a BD».")
    return month_matrix_from_dataframe(df, f"dbo.{table}")


@lru_cache(maxsize=8)
def load_sources(eje_path: str, ppto_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    eje = _read_month_matrix(Path(eje_path), sheet_name="EJE")
    ppto = _read_month_matrix(Path(ppto_path), sheet_name="PPTO")
    return eje, ppto


def available_month_keys(df: pd.DataFrame) -> list[str]:
    return [m for (m, _) in MONTHS_ES if m in df.columns]


def month_label(month_key: str) -> str:
    for k, lbl in MONTHS_ES:
        if k == month_key:
            return lbl
    return month_key


def accumulated(df: pd.DataFrame, month_key: str) -> pd.Series:
    months = available_month_keys(df)
    if month_key not in months:
        raise ValueError(f"Mes inválido: {month_key}")
    idx = months.index(month_key)
    cols = months[: idx + 1]
    return df[cols].sum(axis=1)


def build_report(eje_df: pd.DataFrame, ppto_df: pd.DataFrame, month_key: str) -> dict:
    eje_acc = accumulated(eje_df, month_key)
    ppto_acc = accumulated(ppto_df, month_key)
    ppto_year = accumulated(ppto_df, "Dic") if "Dic" in available_month_keys(ppto_df) else accumulated(ppto_df, month_key)
    eje_year = accumulated(eje_df, "Dic") if "Dic" in available_month_keys(eje_df) else accumulated(eje_df, month_key)

    items_frame = eje_df[["ind", "concepto", "indent", "nivel"]].copy()
    items_frame["parent_ind"] = items_frame["ind"].map(_parent_ind)

    items_frame["eje"] = eje_acc.values
    items_frame["ppto"] = ppto_acc.values
    items_frame["ejeAnual"] = eje_year.values
    items_frame["pptoAnual"] = ppto_year.values

    items_frame["desviacion_pct"] = 0.0
    mask = items_frame["ppto"] != 0
    items_frame.loc[mask, "desviacion_pct"] = (
        items_frame.loc[mask, "eje"] / items_frame.loc[mask, "ppto"] - 1.0
    ) * 100.0

    def status(pct: float) -> str:
        if pct <= -5:
            return "OPTIMAL"
        if pct < 5:
            return "ESTABLE"
        return "REVISIÓN"

    items_frame["estado"] = items_frame["desviacion_pct"].map(status)

    total_eje = float(eje_acc.iloc[0]) if len(eje_acc) else 0.0
    total_ppto = float(ppto_acc.iloc[0]) if len(ppto_acc) else 0.0
    total_ppto_year = float(ppto_year.iloc[0]) if len(ppto_year) else 0.0
    total_eje_year = float(eje_year.iloc[0]) if len(eje_year) else 0.0
    cumplimiento = (total_eje / total_ppto * 100.0) if total_ppto else 0.0

    def _parent_json(v: object) -> str | None:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip()
        return s if s else None

    items = [
        {
            "id": int(idx),
            "ind": str(r.ind),
            "parentInd": _parent_json(r.parent_ind),
            "concepto": str(r.concepto),
            "indent": int(r.indent),
            "nivel": int(r.nivel),
            "eje": float(r.eje),
            "ppto": float(r.ppto),
            "ejeAnual": float(r.ejeAnual),
            "pptoAnual": float(r.pptoAnual),
            "desviacionPct": float(r.desviacion_pct),
            "estado": str(r.estado),
        }
        for idx, r in enumerate(items_frame.itertuples(index=False))
    ]

    return {
        "schemaVersion": 3,
        "mes": month_key,
        "mesLabel": month_label(month_key),
        "totales": {
            "eje": total_eje,
            "ppto": total_ppto,
            "ejeAnual": total_eje_year,
            "pptoAnual": total_ppto_year,
            "desviacionPct": ((total_eje / total_ppto - 1.0) * 100.0) if total_ppto else 0.0,
            "cumplimientoPct": float(cumplimiento),
        },
        "items": items,
    }


def build_series(eje_df: pd.DataFrame, ppto_df: pd.DataFrame, row_id: int) -> dict:
    months = available_month_keys(eje_df)
    if not months:
        raise ValueError("No se encontraron meses en el archivo.")

    if row_id < 0 or row_id >= len(eje_df):
        raise ValueError(f"id inválido: {row_id}")

    eje_row = eje_df.iloc[row_id]
    ppto_row = ppto_df.iloc[row_id]

    eje_monthly = [max(0.0, float(eje_row.get(m, 0.0) or 0.0)) for m in months]
    ppto_monthly = [max(0.0, float(ppto_row.get(m, 0.0) or 0.0)) for m in months]

    eje_acc = []
    ppto_acc = []
    s1 = 0.0
    s2 = 0.0
    for a, b in zip(eje_monthly, ppto_monthly, strict=False):
        s1 += a
        s2 += b
        eje_acc.append(float(s1))
        ppto_acc.append(float(s2))

    return {
        "id": int(row_id),
        "concepto": str(eje_row.get("concepto", "")),
        "months": [{"key": m, "label": month_label(m)} for m in months],
        "monthly": {"eje": eje_monthly, "ppto": ppto_monthly},
        "accumulated": {"eje": eje_acc, "ppto": ppto_acc},
    }
