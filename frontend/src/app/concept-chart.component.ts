import { AfterViewInit, Component, ElementRef, Input, OnChanges, SimpleChanges, ViewChild } from '@angular/core';

import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Filler,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip
} from 'chart.js';

import type { SeriesResponse } from './api.types';

Chart.register(
  CategoryScale,
  LinearScale,
  BarController,
  BarElement,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
  Legend,
  Filler
);

@Component({
  selector: 'app-concept-chart',
  standalone: true,
  template: `
    <div class="bg-surface-container-lowest rounded-3xl border border-outline-variant/15 p-6 h-full">
      <div class="flex items-start justify-between gap-4 mb-4">
        <div>
          <h4 class="text-sm font-extrabold text-slate-800">Tendencia mensual</h4>
          <p class="text-xs text-slate-500">{{ title ?? '—' }}</p>
        </div>
      </div>
      <div class="relative h-[360px]">
        <canvas #canvas></canvas>
      </div>
      <p class="text-[10px] text-slate-400 mt-3">
        Barras: mensual. Líneas: acumulado (eje derecho).
      </p>
    </div>
  `
})
export class ConceptChartComponent implements AfterViewInit, OnChanges {
  @Input() series: SeriesResponse | null = null;
  @Input() title: string | null = null;

  @ViewChild('canvas', { static: true }) canvas!: ElementRef<HTMLCanvasElement>;

  private chart: Chart | null = null;

  private readonly fmtM1 = new Intl.NumberFormat('es-CO', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1
  });

  private toM(v: unknown): number {
    const n = typeof v === 'number' ? v : Number(v);
    if (!isFinite(n)) return 0;
    return n / 1_000_000;
  }

  private fmtAxis = (v: unknown) => `${this.fmtM1.format(this.toM(v))}M`;

  ngAfterViewInit() {
    this.render();
  }

  ngOnChanges(changes: SimpleChanges) {
    if (changes['series'] && this.canvas) this.render();
  }

  private render() {
    const s = this.series;
    if (!s) return;

    const labels = s.months.map((m) => m.key);

    const ctx = this.canvas.nativeElement.getContext('2d');
    if (!ctx) return;

    if (this.chart) {
      this.chart.destroy();
      this.chart = null;
    }

    this.chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            type: 'bar',
            label: 'PPTO mensual',
            data: s.monthly.ppto,
            backgroundColor: 'rgba(0, 169, 157, 0.30)', // #00A99D
            borderColor: 'rgba(0, 169, 157, 0.0)',
            yAxisID: 'y',
            borderRadius: 8,
            barThickness: 10
          },
          {
            type: 'bar',
            label: 'Ejecutado mensual',
            data: s.monthly.eje,
            backgroundColor: 'rgba(45, 90, 112, 0.88)', // #2D5A70
            yAxisID: 'y',
            borderRadius: 8,
            barThickness: 10
          },
          {
            type: 'line',
            label: 'PPTO acumulado',
            data: s.accumulated.ppto,
            yAxisID: 'y1',
            borderColor: 'rgba(0, 169, 157, 0.95)', // #00A99D
            backgroundColor: 'rgba(0, 169, 157, 0.12)',
            fill: true,
            tension: 0.3,
            pointRadius: 2
          },
          {
            type: 'line',
            label: 'Ejecutado acumulado',
            data: s.accumulated.eje,
            yAxisID: 'y1',
            borderColor: 'rgba(13, 148, 136, 1)', // #0D9488
            backgroundColor: 'rgba(13, 148, 136, 0.10)',
            fill: true,
            tension: 0.3,
            pointRadius: 2
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10 } },
          tooltip: {
            enabled: true,
            usePointStyle: true,
            callbacks: {
              label: (ctx) => {
                const label = ctx.dataset.label ?? '';
                const v = this.toM(ctx.parsed?.y);
                return `${label}: ${this.fmtM1.format(v)}M`;
              },
              labelPointStyle: (ctx) => {
                const isLine = (ctx.dataset as { type?: string }).type === 'line';
                return { pointStyle: isLine ? 'line' : 'rectRounded', rotation: 0 };
              }
            }
          }
        },
        scales: {
          x: { grid: { display: false } },
          y: {
            position: 'left',
            grid: { color: 'rgba(148, 163, 184, 0.25)' },
            ticks: { callback: this.fmtAxis }
          },
          y1: {
            position: 'right',
            grid: { drawOnChartArea: false },
            ticks: { callback: this.fmtAxis }
          }
        }
      }
    });
  }
}

