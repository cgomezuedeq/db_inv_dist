import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe, NgClass } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';

import { ApiService } from './api.service';
import type { MonthOption, ReportItem, ReportResponse, SeriesResponse } from './api.types';
import { ConceptChartComponent } from './concept-chart.component';

@Component({
  selector: 'app-root',
  imports: [DecimalPipe, NgClass, ConceptChartComponent],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  private readonly api = inject(ApiService);

  protected readonly Math = Math;

  protected readonly months = signal<MonthOption[]>([]);
  protected readonly selectedMonth = signal<string>('Dic');
  /** 2024 … año en curso (mismo orden que el ``<select>``). */
  protected readonly yearOptions = Array.from(
    { length: new Date().getFullYear() - 2024 + 1 },
    (_, i) => 2024 + i
  );

  /** Año de las tablas SQL ``dbo.sd_inv_{año}_EJE`` / ``PPTO`` (y año de carga Excel). Siempre inicia en el año en curso. */
  protected readonly uploadYear = signal<number>(
    this.yearOptions.length ? this.yearOptions[this.yearOptions.length - 1]! : new Date().getFullYear()
  );
  protected readonly report = signal<ReportResponse | null>(null);
  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly uploadLoading = signal<boolean>(false);
  protected readonly uploadMessage = signal<string | null>(null);

  /** Subárboles abiertos en la lista (valores IND). */
  protected readonly expandedInds = signal<Set<string>>(new Set());
  /** Raíz del bloque mostrado (IND de primer nivel: sin padre en el archivo). */
  protected readonly selectedRootInd = signal<string | null>(null);
  protected readonly selectedItemId = signal<number | null>(null);
  protected readonly selectedSeries = signal<SeriesResponse | null>(null);
  protected readonly selectedTitle = signal<string | null>(null);

  /** Filas con IND de primer nivel (varios árboles en el mismo Excel). */
  protected readonly topLevelParents = computed(() =>
    (this.report()?.items ?? []).filter((i) => i.parentInd == null)
  );

  /** Totales KPI y serie «resumen» del bloque elegido (fila del IND raíz). */
  protected readonly viewTotals = computed(() => {
    const r = this.report();
    const ind = this.selectedRootInd();
    if (!r?.items?.length) {
      return null;
    }
    const root = ind != null ? r.items.find((x) => x.ind === ind) : r.items[0];
    if (!root) {
      return r.totales;
    }
    const ppto = isFinite(root.ppto) ? root.ppto : 0;
    const eje = isFinite(root.eje) ? root.eje : 0;
    return {
      eje,
      ppto,
      ejeAnual: root.ejeAnual,
      pptoAnual: root.pptoAnual,
      desviacionPct: root.desviacionPct,
      cumplimientoPct: ppto > 0 ? (eje / ppto) * 100 : 0
    };
  });

  protected readonly totalItemId = computed(() => {
    const items = this.report()?.items ?? [];
    const ind = this.selectedRootInd();
    if (ind == null) {
      return items[0]?.id ?? 0;
    }
    return items.find((x) => x.ind === ind)?.id ?? items[0]?.id ?? 0;
  });

  /** Hijos por IND padre (solo nodos con `parentInd` definido). */
  private readonly childrenByParent = computed(() => {
    const m = new Map<string, ReportItem[]>();
    for (const it of this.report()?.items ?? []) {
      const p = it.parentInd;
      if (p == null || p === '') {
        continue;
      }
      const k = p;
      if (!m.has(k)) {
        m.set(k, []);
      }
      m.get(k)!.push(it);
    }
    return m;
  });

  protected hasChildren(ind: string): boolean {
    return (this.childrenByParent().get(ind)?.length ?? 0) > 0;
  }

  /** Barras: hijas/nietas del IND raíz elegido (sin repetir la fila raíz). */
  protected readonly barsView = computed(() => {
    const rootInd = this.selectedRootInd();
    const expanded = this.expandedInds();
    const byParent = this.childrenByParent();
    const out: Array<{ item: ReportItem; isChild: boolean; indentPx: number }> = [];

    if (rootInd == null) {
      return out;
    }

    const walk = (parentInd: string, baseIndent: number) => {
      const kids = byParent.get(parentInd);
      if (!kids?.length) {
        return;
      }
      const directOfRoot = parentInd === rootInd;
      for (const child of kids) {
        out.push({
          item: child,
          isChild: !directOfRoot,
          indentPx: baseIndent
        });
        if (expanded.has(child.ind)) {
          walk(child.ind, baseIndent + (directOfRoot ? 24 : 16));
        }
      }
    };

    walk(rootInd, 0);
    return out;
  });

  constructor() {
    this.loading.set(true);
    // Ya no filtramos por mes: se muestra el total (Dic / cierre).
    this.refresh();
  }

  protected onUploadYearChange(ev: Event) {
    const el = ev.target as HTMLSelectElement;
    this.uploadYear.set(Number(el.value));
    this.refresh();
  }

  protected onRootBlockChange(ev: Event) {
    const el = ev.target as HTMLSelectElement;
    const ind = el.value;
    this.selectedRootInd.set(ind);
    this.expandedInds.set(new Set());
    const id = this.report()?.items?.find((x) => x.ind === ind)?.id ?? null;
    if (id != null) {
      this.selectForChart(id, false);
    }
  }

  protected onDbExcelSelected(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;

    this.uploadLoading.set(true);
    this.uploadMessage.set(null);
    this.api.uploadExcelToDb(this.uploadYear(), file).subscribe({
      next: (res) => {
        this.uploadMessage.set(`Carga en SQL correcta: ${res.tables.join(', ')}`);
        this.uploadLoading.set(false);
        this.refresh();
      },
      error: (err: HttpErrorResponse) => {
        const d = err.error?.detail;
        const msg =
          typeof d === 'string'
            ? d
            : Array.isArray(d)
              ? d.map((x: { msg?: string }) => x?.msg ?? '').join(' ')
              : 'No se pudo cargar el archivo en la base de datos.';
        this.uploadMessage.set(msg);
        this.uploadLoading.set(false);
      }
    });
  }

  protected refresh() {
    this.selectedMonth.set('Dic');
    const m = 'Dic';
    this.loading.set(true);
    this.error.set(null);
    this.api.getReport(m, this.uploadYear()).subscribe({
      next: (r) => {
        this.report.set(r);
        this.expandedInds.set(new Set());
        const roots = r.items?.filter((i) => i.parentInd == null) ?? [];
        const firstInd = roots[0]?.ind ?? r.items?.[0]?.ind ?? null;
        this.selectedRootInd.set(firstInd);
        this.loading.set(false);
        const current = this.selectedItemId();
        const blockRootId = firstInd != null ? r.items?.find((x) => x.ind === firstInd)?.id : r.items?.[0]?.id;
        const fallback = blockRootId ?? r.items?.[0]?.id ?? null;
        this.selectForChart(current ?? fallback, false);
      },
      error: (err: HttpErrorResponse) => {
        const hint =
          err.status === 0
            ? ' No hay conexión con el API: arranque el backend (carpeta backend) y use el mismo puerto que `frontend/proxy.conf.json` → target (p. ej. python -m uvicorn app:app --reload --port 8001).'
            : '';
        const detail =
          typeof err.error?.detail === 'string'
            ? err.error.detail
            : err.error?.detail != null
              ? JSON.stringify(err.error.detail)
              : err.message;
        this.error.set(
          `No fue posible cargar el reporte.${hint}` +
            (err.status ? ` (HTTP ${err.status}${detail ? `: ${detail}` : ''})` : '')
        );
        this.loading.set(false);
      }
    });
  }

  protected mmValue(value: number): number {
    if (!isFinite(value)) return 0;
    return value / 1e6;
  }

  protected n(value: number): string {
    const v = isFinite(value) ? value : 0;
    return new Intl.NumberFormat('es-CO').format(v);
  }

  protected n1(value: number): string {
    const v = isFinite(value) ? value : 0;
    return new Intl.NumberFormat('es-CO', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(v);
  }

  protected toggleExpandInd(ind: string) {
    const next = new Set(this.expandedInds());
    if (next.has(ind)) {
      next.delete(ind);
    } else {
      next.add(ind);
    }
    this.expandedInds.set(next);
  }

  protected onBarClick(row: { item: ReportItem; isChild: boolean; indentPx: number }) {
    if (this.hasChildren(row.item.ind)) {
      this.toggleExpandInd(row.item.ind);
    }
    this.selectForChart(row.item.id);
  }

  protected selectTotalForChart() {
    this.selectForChart(this.totalItemId());
  }

  protected selectForChart(id: number | null, userInitiated = true) {
    if (id == null) return;
    if (userInitiated) this.selectedItemId.set(id);
    const items = this.report()?.items ?? [];
    const it = items.find((x) => x.id === id);
    const rootIt = items.find((x) => x.id === this.totalItemId());
    const rootLabel = rootIt?.concepto ?? 'Bloque';
    this.selectedTitle.set(id === this.totalItemId() ? rootLabel : (it?.concepto ?? null));
    this.api.getSeries(id, this.uploadYear()).subscribe({
      next: (s) => this.selectedSeries.set(s),
      error: () => this.selectedSeries.set(null)
    });
  }

  protected barPct(value: number, denom: number): number {
    if (!isFinite(value) || !isFinite(denom) || denom <= 0) return 0;
    return Math.max(0, Math.min(100, (value / denom) * 100));
  }

  protected barMinPx(value: number, denom: number): number {
    return this.barPct(value, denom) > 0 ? 2 : 0;
  }

  protected isOver(value: number, denom: number): boolean {
    return isFinite(value) && isFinite(denom) && denom > 0 && value > denom;
  }

  protected denomFor(item: ReportItem): number {
    const month = this.selectedMonth();
    const ppto = isFinite(item.ppto) ? item.ppto : 0;

    // En diciembre, el acumulado del mes ya representa el anual del concepto.
    if (month === 'Dic') return ppto;

    // Estimación del anual del concepto a partir de la participación del acumulado del mes.
    const tot = (this.viewTotals() ?? this.report()?.totales) as unknown as { pptoAnual?: number; ppto?: number } | undefined;
    const totalAnual = isFinite(tot?.pptoAnual ?? NaN) ? (tot?.pptoAnual ?? 0) : 0;
    const totalAcum = isFinite(tot?.ppto ?? NaN) ? (tot?.ppto ?? 0) : 0;

    if (totalAnual > 0 && totalAcum > 0 && ppto > 0) {
      return totalAnual * (ppto / totalAcum);
    }

    // Fallback para no dejar barras en 0 cuando falte info.
    return ppto;
  }

  protected overClass(value: number, denom: number): string {
    if (!this.isOver(value, denom)) return '';
    return [
      'outline',
      'outline-4',
      'outline-amber-400',
      'shadow-[0_0_0_6px_rgba(251,191,36,0.28)]',
      'drop-shadow-[0_10px_18px_rgba(251,191,36,0.18)]'
    ].join(' ');
  }

  protected pct(value: number): string {
    if (!isFinite(value)) return '0%';
    const s = value >= 0 ? '+' : '';
    return `${s}${value.toFixed(1)}%`;
  }

  protected estadoClass(item: ReportItem): string {
    switch (item.estado) {
      case 'OPTIMAL':
        return 'bg-emerald-100 text-emerald-800';
      case 'ESTABLE':
        return 'bg-slate-100 text-slate-600';
      default:
        return 'bg-rose-100 text-tertiary';
    }
  }

  protected estadoDotClass(item: ReportItem): string {
    switch (item.estado) {
      case 'OPTIMAL':
        return 'bg-emerald-600';
      case 'ESTABLE':
        return 'bg-slate-400';
      default:
        return 'bg-tertiary';
    }
  }
}
