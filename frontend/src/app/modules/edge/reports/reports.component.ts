import { Component, Inject, PLATFORM_ID } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';
import { AuthService } from 'src/app/core/services/auth.service';

export type ReportKind = 'Scan summary' | 'Alerts' | 'Blacklist activity';
export type ReportFormat = 'CSV' | 'JSON' | 'PDF';
export type Preset = 'day' | 'week' | 'month' | 'custom';

/** One day of aggregated lane activity — the unit every report is built from. */
export interface DayRow {
  date: string;
  scans: number;
  cleared: number;
  watch: number;
  blacklist: number;
  halted: number;
  avgRisk: number;
}

interface GeneratedReport {
  name: string;
  kind: ReportKind;
  format: ReportFormat;
  range: string;
  days: number;
  rows: number;
  generatedAt: string;
}

const MS_DAY = 86_400_000;

@Component({
  selector: 'app-edge-reports',
  templateUrl: './reports.component.html',
  styleUrls: ['./reports.component.css'],
})
export class ReportsComponent {
  readonly kinds: ReportKind[] = ['Scan summary', 'Alerts', 'Blacklist activity'];
  readonly formats: ReportFormat[] = ['CSV', 'JSON', 'PDF'];

  kind: ReportKind = 'Scan summary';
  format: ReportFormat = 'CSV';
  preset: Preset = 'week';

  /** Bound to <input type="date"> — always yyyy-MM-dd. */
  start = '';
  end = '';

  error = '';
  recent: GeneratedReport[] = [];

  private readonly isBrowser: boolean;

  constructor(
    @Inject(PLATFORM_ID) platformId: Object,
    private auth: AuthService,
  ) {
    this.isBrowser = isPlatformBrowser(platformId);
    this.applyPreset('week');
  }

  // ── date range ──────────────────────────────────────────────────────────
  private static iso(d: Date): string {
    return [
      d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, '0'),
      String(d.getDate()).padStart(2, '0'),
    ].join('-');
  }

  /** Today / last 7 days / last 30 days. 'custom' leaves the pickers alone. */
  applyPreset(p: Preset): void {
    this.preset = p;
    this.error = '';
    if (p === 'custom') return;

    const today = new Date();
    const back = p === 'day' ? 0 : p === 'week' ? 6 : 29;
    const from = new Date(today.getTime() - back * MS_DAY);
    this.start = ReportsComponent.iso(from);
    this.end = ReportsComponent.iso(today);
  }

  /** Editing either picker switches the preset chips to Custom. */
  onDateEdited(): void {
    this.preset = 'custom';
    this.error = '';
  }

  private parse(s: string): Date | null {
    const parts = s.split('-').map(Number);
    if (parts.length !== 3 || parts.some(isNaN)) return null;
    return new Date(parts[0], parts[1] - 1, parts[2]);
  }

  get dayCount(): number {
    const a = this.parse(this.start);
    const b = this.parse(this.end);
    if (!a || !b) return 0;
    const n = Math.round((b.getTime() - a.getTime()) / MS_DAY) + 1;
    return n > 0 ? n : 0;
  }

  get rangeLabel(): string {
    if (!this.dayCount) return '—';
    return this.start + ' → ' + this.end + ' · ' + this.dayCount + (this.dayCount === 1 ? ' day' : ' days');
  }

  // ── data ────────────────────────────────────────────────────────────────
  /**
   * Stand-in for the scan archive until the backend exposes one. Seeded off the
   * date so a given range always renders and exports the same numbers.
   */
  private seeded(date: string, salt: number): number {
    // FNV-1a plus an avalanche step — a plain h*31 hash leaves consecutive
    // dates within rounding distance of each other and every day looks alike.
    let h = 2166136261 ^ salt;
    for (let i = 0; i < date.length; i++) {
      h ^= date.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    h ^= h >>> 13;
    h = Math.imul(h, 0x5bd1e995);
    h ^= h >>> 15;
    return ((h >>> 0) % 100000) / 100000;
  }

  get rows(): DayRow[] {
    const a = this.parse(this.start);
    const n = this.dayCount;
    if (!a || !n) return [];

    const out: DayRow[] = [];
    for (let i = 0; i < n; i++) {
      const d = new Date(a.getTime() + i * MS_DAY);
      const date = ReportsComponent.iso(d);
      const weekend = d.getDay() === 5 || d.getDay() === 6;

      const scans = Math.round(38 + this.seeded(date, 7) * 70) - (weekend ? 18 : 0);
      const blacklist = Math.round(this.seeded(date, 13) * 4);
      const watch = Math.round(this.seeded(date, 29) * 7);
      const halted = Math.min(scans, blacklist + Math.round(this.seeded(date, 43) * 3));
      const cleared = Math.max(0, scans - blacklist - watch);
      const avgRisk = Math.round(12 + this.seeded(date, 71) * 26);

      out.push({ date, scans, cleared, watch, blacklist, halted, avgRisk });
    }
    return out;
  }

  /** Rows narrowed to what the selected report kind actually reports on. */
  get reportRows(): DayRow[] {
    if (this.kind === 'Alerts') return this.rows.filter((r) => r.watch + r.blacklist > 0);
    if (this.kind === 'Blacklist activity') return this.rows.filter((r) => r.blacklist > 0);
    return this.rows;
  }

  get totals() {
    return this.reportRows.reduce(
      (t, r) => ({
        scans: t.scans + r.scans,
        cleared: t.cleared + r.cleared,
        watch: t.watch + r.watch,
        blacklist: t.blacklist + r.blacklist,
        halted: t.halted + r.halted,
      }),
      { scans: 0, cleared: 0, watch: 0, blacklist: 0, halted: 0 },
    );
  }

  get avgRisk(): number {
    const rs = this.reportRows;
    if (!rs.length) return 0;
    return Math.round(rs.reduce((n, r) => n + r.avgRisk, 0) / rs.length);
  }

  // ── export ──────────────────────────────────────────────────────────────
  private validate(): boolean {
    const a = this.parse(this.start);
    const b = this.parse(this.end);
    if (!a || !b) { this.error = 'Pick a start and an end date.'; return false; }
    if (b.getTime() < a.getTime()) { this.error = 'The end date is before the start date.'; return false; }
    if (this.dayCount > 366) { this.error = 'Range is longer than a year — narrow it down.'; return false; }
    if (!this.reportRows.length) { this.error = 'No records in that range for this report type.'; return false; }
    this.error = '';
    return true;
  }

  private fileName(ext: string): string {
    const slug = this.kind.toLowerCase().replace(/[^a-z]+/g, '-');
    return `uvss-edge-${slug}-${this.start}_to_${this.end}.${ext}`;
  }

  private toCsv(): string {
    const head = ['Date', 'Scans', 'Cleared', 'Watch hits', 'Blacklist hits', 'Halted', 'Avg risk'];
    const body = this.reportRows.map((r) =>
      [r.date, r.scans, r.cleared, r.watch, r.blacklist, r.halted, r.avgRisk].join(','),
    );
    const t = this.totals;
    const foot = ['TOTAL', t.scans, t.cleared, t.watch, t.blacklist, t.halted, this.avgRisk].join(',');
    return [
      `# UVSS Edge · ${this.kind}`,
      `# Site,BNS Issa Khan`,
      `# Range,${this.start} to ${this.end}`,
      `# Generated by,${this.auth.username('edge')}`,
      '',
      head.join(','),
      ...body,
      foot,
    ].join('\n');
  }

  private toJson(): string {
    return JSON.stringify(
      {
        report: this.kind,
        site: 'BNS Issa Khan',
        range: { start: this.start, end: this.end, days: this.dayCount },
        generatedBy: this.auth.username('edge'),
        generatedAt: new Date().toISOString(),
        totals: { ...this.totals, avgRisk: this.avgRisk },
        days: this.reportRows,
      },
      null,
      2,
    );
  }

  private download(content: string, mime: string, name: string): void {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  /** Everything interpolated into the print document goes through this first. */
  private static esc(v: unknown): string {
    return String(v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * PDF has no client-side generator here, so the report is rendered into a
   * sandboxed print frame — "Save as PDF" in the browser's print dialog
   * produces the file.
   */
  private printPdf(): void {
    const esc = ReportsComponent.esc;
    const t = this.totals;
    const rows = this.reportRows
      .map(
        (r) =>
          `<tr><td>${r.date}</td><td>${r.scans}</td><td>${r.cleared}</td><td>${r.watch}</td><td>${r.blacklist}</td><td>${r.halted}</td><td>${r.avgRisk}</td></tr>`,
      )
      .join('');

    const html = `<!doctype html><html><head><meta charset="utf-8"><title>${esc(this.fileName('pdf'))}</title>
<style>
 body{font:12px/1.5 system-ui,sans-serif;color:#111;margin:32px;}
 h1{font-size:18px;margin:0 0 4px;} .sub{color:#666;font-size:11px;margin-bottom:18px;}
 .kpis{display:flex;gap:22px;margin-bottom:18px;}
 .kpi b{display:block;font-size:20px;} .kpi span{color:#666;font-size:10px;text-transform:uppercase;letter-spacing:.05em;}
 table{border-collapse:collapse;width:100%;font-size:11px;}
 th,td{border:1px solid #ddd;padding:5px 8px;text-align:right;} th:first-child,td:first-child{text-align:left;}
 th{background:#f4f4f5;} tfoot td{font-weight:700;background:#fafafa;}
</style></head><body>
<h1>UVSS Edge · ${esc(this.kind)}</h1>
<div class="sub">BNS Issa Khan · ${esc(this.start)} to ${esc(this.end)} (${this.dayCount} days) · generated by ${esc(this.auth.username('edge'))}</div>
<div class="kpis">
 <div class="kpi"><b>${t.scans}</b><span>Scans</span></div>
 <div class="kpi"><b>${t.blacklist}</b><span>Blacklist hits</span></div>
 <div class="kpi"><b>${t.watch}</b><span>Watch hits</span></div>
 <div class="kpi"><b>${t.halted}</b><span>Halted</span></div>
 <div class="kpi"><b>${this.avgRisk}</b><span>Avg risk</span></div>
</div>
<table><thead><tr><th>Date</th><th>Scans</th><th>Cleared</th><th>Watch</th><th>Blacklist</th><th>Halted</th><th>Avg risk</th></tr></thead>
<tbody>${rows}</tbody>
<tfoot><tr><td>Total</td><td>${t.scans}</td><td>${t.cleared}</td><td>${t.watch}</td><td>${t.blacklist}</td><td>${t.halted}</td><td>${this.avgRisk}</td></tr></tfoot>
</table></body></html>`;

    // An offscreen srcdoc frame rather than a popup: no pop-up blocker to fight,
    // and nothing is ever written into the host document.
    const frame = document.createElement('iframe');
    frame.setAttribute('sandbox', 'allow-modals allow-same-origin');
    frame.setAttribute('aria-hidden', 'true');
    frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;';
    frame.srcdoc = html;
    frame.onload = () => {
      const w = frame.contentWindow;
      if (!w) { frame.remove(); return; }
      // Tear the frame down only once the dialog is done with it — a fixed
      // timer can pull it out from under an open print dialog.
      let done = false;
      const drop = () => { if (!done) { done = true; frame.remove(); } };
      w.addEventListener('afterprint', drop);
      w.focus();
      w.print();
      // Fallback for browsers that never fire afterprint.
      setTimeout(drop, 60_000);
    };
    document.body.appendChild(frame);
  }

  generate(): void {
    if (!this.isBrowser || !this.validate()) return;

    if (this.format === 'CSV') {
      this.download(this.toCsv(), 'text/csv;charset=utf-8', this.fileName('csv'));
    } else if (this.format === 'JSON') {
      this.download(this.toJson(), 'application/json;charset=utf-8', this.fileName('json'));
    } else {
      this.printPdf();
    }

    this.recent = [
      {
        name: this.fileName(this.format.toLowerCase()),
        kind: this.kind,
        format: this.format,
        range: this.start + ' → ' + this.end,
        days: this.dayCount,
        rows: this.reportRows.length,
        generatedAt: new Date().toISOString(),
      },
      ...this.recent,
    ].slice(0, 6);
  }
}
