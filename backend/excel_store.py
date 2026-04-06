from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import unicodedata

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

def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    # "Reposici�n" (mojibake) cae aquí; quitamos caracteres no ASCII útiles.
    s = s.replace("�", "")
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return " ".join(s.split())


LEVEL2_CONCEPTS_NORM = {
    _norm_text("Reposición y Modernización"),
    _norm_text("Expansión Redes"),
    _norm_text("Subestaciones"),
    _norm_text("Consolidación de Centros de Control"),
}


@dataclass(frozen=True)
class ExcelSources:
    eje_path: Path
    ppto_path: Path


def _read_month_matrix(path: Path, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet_name)

    first_col = df.columns[0]
    df = df.rename(columns={first_col: "concepto_raw"})

    keep_cols = ["concepto_raw"] + [m for (m, _) in MONTHS_ES if m in df.columns]
    df = df[keep_cols].copy()

    df["concepto_raw"] = df["concepto_raw"].astype(str)
    df["concepto"] = df["concepto_raw"].str.strip()
    df["indent"] = df["concepto_raw"].str.len() - df["concepto_raw"].str.lstrip().str.len()

    for m, _ in MONTHS_ES:
        if m in df.columns:
            df[m] = pd.to_numeric(df[m], errors="coerce").fillna(0.0)

    return df


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


def _infer_levels_from_indent(indent: pd.Series) -> pd.Series:
    # Normaliza niveles según valores únicos de sangría en el archivo.
    # Ejemplo típico: [0, 14, 24] => niveles [1, 2, 3]
    uniq = sorted({int(x) for x in indent.fillna(0).astype(int).tolist()})
    mapping = {v: i + 1 for i, v in enumerate(uniq)}
    return indent.fillna(0).astype(int).map(mapping).fillna(1).astype(int)


def _infer_levels_from_concepts(concepto: pd.Series) -> pd.Series:
    # Fallback cuando el Excel no trae sangrías (celdas sin espacios al inicio).
    # Regla: primera fila = nivel 1; las filas cuyo concepto esté en LEVEL2_CONCEPTS
    # se consideran nivel 2 (padres) y las filas entre padres son nivel 3.
    levels: list[int] = []
    prev_parent: str | None = None

    for idx, raw in enumerate(concepto.astype(str).tolist()):
        c = raw.strip()
        c_norm = _norm_text(c)
        if idx == 0:
            levels.append(1)
            continue

        if c_norm in LEVEL2_CONCEPTS_NORM and c != prev_parent:
            levels.append(2)
            prev_parent = c
        else:
            levels.append(3 if prev_parent is not None else 2)

    return pd.Series(levels, index=concepto.index)


def build_report(eje_df: pd.DataFrame, ppto_df: pd.DataFrame, month_key: str) -> dict:
    eje_acc = accumulated(eje_df, month_key)
    ppto_acc = accumulated(ppto_df, month_key)
    ppto_year = accumulated(ppto_df, "Dic") if "Dic" in available_month_keys(ppto_df) else accumulated(ppto_df, month_key)
    eje_year = accumulated(eje_df, "Dic") if "Dic" in available_month_keys(eje_df) else accumulated(eje_df, month_key)

    eje_items = eje_df[["concepto", "indent"]].copy()
    eje_items["eje"] = eje_acc
    eje_items["ppto"] = ppto_acc
    eje_items["ejeAnual"] = eje_year
    eje_items["pptoAnual"] = ppto_year
    inferred = _infer_levels_from_indent(eje_items["indent"])
    if inferred.nunique(dropna=True) <= 1:
        inferred = _infer_levels_from_concepts(eje_items["concepto"])
    eje_items["nivel"] = inferred

    eje_items["desviacion_pct"] = 0.0
    mask = eje_items["ppto"] != 0
    eje_items.loc[mask, "desviacion_pct"] = (eje_items.loc[mask, "eje"] / eje_items.loc[mask, "ppto"] - 1.0) * 100.0

    def status(pct: float) -> str:
        if pct <= -5:
            return "OPTIMAL"
        if pct < 5:
            return "ESTABLE"
        return "REVISIÓN"

    eje_items["estado"] = eje_items["desviacion_pct"].map(status)

    total_eje = float(eje_items["eje"].iloc[0]) if len(eje_items) else 0.0
    total_ppto = float(eje_items["ppto"].iloc[0]) if len(eje_items) else 0.0
    total_ppto_year = float(ppto_year.iloc[0]) if len(eje_items) else 0.0
    total_eje_year = float(eje_year.iloc[0]) if len(eje_items) else 0.0
    cumplimiento = (total_eje / total_ppto * 100.0) if total_ppto else 0.0

    items = [
        {
            "id": int(idx),
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
        for idx, r in enumerate(eje_items.itertuples(index=False))
    ]

    return {
        "schemaVersion": 2,
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

    # Para la visualización, evitamos valores negativos (ajustes contables) que
    # distorsionan la escala y confunden al usuario. Si necesitas verlos, lo
    # manejamos como un toggle más adelante.
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

