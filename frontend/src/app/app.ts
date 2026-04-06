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
  /** Solo para la carga a SQL Server; el reporte sigue usando EJE.xlsx / PPTO.xlsx locales. */
  protected readonly uploadYear = signal<number>(new Date().getFullYear());
  protected readonly yearOptions = Array.from({ length: 20 }, (_, i) => new Date().getFullYear() - 10 + i);
  protected readonly report = signal<ReportResponse | null>(null);
  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly uploadLoading = signal<boolean>(false);
  protected readonly uploadMessage = signal<string | null>(null);

  protected readonly expandedConcept = signal<string | null>(null);
  protected readonly selectedItemId = signal<number | null>(null);
  protected readonly selectedSeries = signal<SeriesResponse | null>(null);
  protected readonly selectedTitle = signal<string | null>(null);
  protected readonly totalItemId = computed(() => this.report()?.items?.[0]?.id ?? 0);

  private readonly indentToLevel = computed(() => {
    const items = this.report()?.items ?? [];
    const uniq = Array.from(new Set(items.map((i) => i.indent ?? 0))).sort((a, b) => a - b);
    const map = new Map<number, number>();
    uniq.forEach((v, idx) => map.set(v, idx + 1));
    return map;
  });

  private levelOf(item: ReportItem): number {
    const lvl = (item as unknown as { nivel?: number }).nivel;
    if (typeof lvl === 'number' && isFinite(lvl)) return lvl;
    return this.indentToLevel().get(item.indent ?? 0) ?? 1;
  }

  private readonly level2ConceptsNorm = new Set(
    ['Reposición y Modernización', 'Expansión Redes', 'Subestaciones', 'Consolidación de Centros de Control'].map((s) =>
      this.normText(s)
    )
  );

  private normText(s: string): string {
    return (s ?? '')
      .trim()
      .toLowerCase()
      .replaceAll('�', '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/\s+/g, ' ');
  }

  protected readonly visibleItems = computed(() => {
    const r = this.report();
    return (r?.items ?? []).slice(0);
  });

  private readonly level2Groups = computed(() => {
    const items = this.report()?.items ?? [];
    const groups: { parent: ReportItem; children: ReportItem[] }[] = [];

    const hasUsefulLevels = items.some((it) => this.levelOf(it) !== 1) || this.indentToLevel().size > 1;
    const seenParents = new Set<string>();

    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      const isParent = hasUsefulLevels
        ? this.levelOf(it) === 2
        : i > 0 && this.level2ConceptsNorm.has(this.normText(it.concepto));
      if (!isParent) continue;

      const parentKey = this.normText(it.concepto);
      if (seenParents.has(parentKey)) continue;
      seenParents.add(parentKey);

      const children: ReportItem[] = [];
      for (let j = i + 1; j < items.length; j++) {
        const nxt = items[j];
        if (hasUsefulLevels) {
          const nxtLvl = this.levelOf(nxt);
          if (nxtLvl <= 2) break;
          if (nxtLvl === 3) children.push(nxt);
        } else {
          const nxtKey = this.normText(nxt.concepto);
          const nxtIsParent = this.level2ConceptsNorm.has(nxtKey);
          // Si el Excel repite el mismo concepto padre (ej: "Expansión Redes"),
          // lo tratamos como parte del bloque (hija) y NO como corte.
          const nxtIsDifferentParent = nxtIsParent && nxtKey !== parentKey;
          if (nxtIsDifferentParent) break;
          children.push(nxt);
        }
      }
      groups.push({ parent: it, children });
    }
    return groups;
  });

  protected readonly barsView = computed(() => {
    const exp = this.expandedConcept();
    const out: Array<{ item: ReportItem; isChild: boolean }> = [];
    for (const g of this.level2Groups()) {
      out.push({ item: g.parent, isChild: false });
      if (exp && g.parent.concepto === exp) {
        for (const c of g.children) out.push({ item: c, isChild: true });
      }
    }
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
    this.api.getReport(m).subscribe({
      next: (r) => {
        this.report.set(r);
        this.loading.set(false);
        const current = this.selectedItemId();
        const fallback = r.items?.[0]?.id ?? null;
        this.selectForChart(current ?? fallback, false);
      },
      error: (err: HttpErrorResponse) => {
        const hint =
          err.status === 0
            ? ' No hay conexión con el API: arranque el backend de Dashboard inversiones (carpeta backend) con el mismo puerto que proxy.conf.json (p. ej. python -m uvicorn app:app --reload --port 8000).'
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

  protected toggleExpand(concepto: string) {
    this.expandedConcept.set(this.expandedConcept() === concepto ? null : concepto);
  }

  protected onBarClick(row: { item: ReportItem; isChild: boolean }) {
    if (row.isChild) {
      this.selectForChart(row.item.id);
      return;
    }

    this.toggleExpand(row.item.concepto);
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
    this.selectedTitle.set(id === this.totalItemId() ? 'Total' : (it?.concepto ?? null));
    this.api.getSeries(id).subscribe({
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
    const tot = this.report()?.totales as unknown as { pptoAnual?: number; ppto?: number } | undefined;
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
