import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';

import type { MonthOption, ReportResponse, SeriesResponse, UploadDbResponse } from './api.types';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  getMonths() {
    return this.http.get<MonthOption[]>('/api/v1/months');
  }

  getReport(monthKey: string) {
    return this.http.get<ReportResponse>('/api/v1/report', {
      params: { month: monthKey }
    });
  }

  getSeries(id: number) {
    return this.http.get<SeriesResponse>('/api/v1/series', {
      params: { id }
    });
  }

  /** Carga hojas PPTO y EJE del Excel a SQL Server (no afecta el reporte del dashboard). */
  uploadExcelToDb(year: number, file: File) {
    const fd = new FormData();
    fd.append('year', String(year));
    fd.append('file', file, file.name);
    return this.http.post<UploadDbResponse>('/api/v1/upload', fd);
  }
}

