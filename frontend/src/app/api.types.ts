export type MonthOption = { key: string; label: string };

export type ReportTotals = {
  eje: number;
  ppto: number;
  ejeAnual: number;
  pptoAnual: number;
  desviacionPct: number;
  cumplimientoPct: number;
};

export type ReportItem = {
  id: number;
  /** Codificación jerárquica (p. ej. 1, 1.1, 1.1.1). */
  ind: string;
  /** Padre inmediato en la jerarquía; `null` solo en la raíz IND «1». */
  parentInd: string | null;
  /** Texto del Excel (columna DETALLE). */
  concepto: string;
  indent: number;
  nivel: number;
  eje: number;
  ppto: number;
  ejeAnual: number;
  pptoAnual: number;
  desviacionPct: number;
  estado: 'OPTIMAL' | 'ESTABLE' | 'REVISIÓN';
};

export type SeriesMonth = { key: string; label: string };
export type SeriesResponse = {
  id: number;
  concepto: string;
  months: SeriesMonth[];
  monthly: { eje: number[]; ppto: number[] };
  accumulated: { eje: number[]; ppto: number[] };
};

export type ReportResponse = {
  mes: string;
  mesLabel: string;
  totales: ReportTotals;
  items: ReportItem[];
};

export type UploadDbResponse = {
  ok: boolean;
  year: number;
  tables: string[];
};

