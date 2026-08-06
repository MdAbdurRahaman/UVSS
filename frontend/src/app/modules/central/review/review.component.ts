import { Component } from '@angular/core';

type Resolution = 'halt' | 'clear' | 'escalate';

interface QueueItem {
  id: string;
  site: string;
  plate: string;
  risk: number;
  verdict: string;
  reason: string;
  pos: string;
}

@Component({
  selector: 'app-central-review',
  templateUrl: './review.component.html',
  styleUrls: ['./review.component.css'],
})
export class ReviewComponent {
  sel = 0;
  done: Record<number, Resolution> = {};

  readonly q: QueueItem[] = [
    { id: '#A-2291', site: 'BNS Issa Khan', plate: 'DL 3C AD 8491', risk: 84, verdict: 'Blacklist', reason: 'Operator halted · confirm', pos: 'center' },
    { id: '#C-0884', site: 'Mongla Port', plate: 'DHA GA 09-7733', risk: 71, verdict: 'Blacklist', reason: 'Anomaly region flagged', pos: '30% 40%' },
    { id: '#D-2207', site: 'Payra Port', plate: 'RAJ KHA 33-9921', risk: 64, verdict: 'Anomaly', reason: 'Foreign object near sill', pos: '55% 50%' },
    { id: '#E-0455', site: 'Benapole Port', plate: 'CTG HA 21-4410', risk: 38, verdict: 'Watch', reason: 'Watch plate · baseline diff', pos: '25% 65%' },
    { id: '#B-1042', site: 'Chattogram Port', plate: 'DHA LA 77-3055', risk: 29, verdict: 'Manual', reason: 'Manual hold · operator note', pos: '80% 30%' },
    { id: '#F-3320', site: 'Teknaf Port', plate: 'SYL KHA 55-2017', risk: 26, verdict: 'Watch', reason: 'Repeated crossing', pos: '15% 80%' },
  ];

  thumb(pos: string): string {
    return `url('assets/undercarriage.jpg') ${pos}/200% no-repeat`;
  }

  select(i: number): void {
    this.sel = i;
  }

  resolve(kind: Resolution): void {
    this.done = { ...this.done, [this.sel]: kind };
    for (let k = 0; k < this.q.length; k++) {
      if (!this.done[k]) { this.sel = k; break; }
    }
  }

  private label(k: Resolution): string {
    return k === 'halt' ? 'Halted' : k === 'clear' ? 'Cleared' : 'Escalated';
  }

  // ── queue row helpers ──
  // Colors resolve through the design-system tokens so they follow the theme.
  rowBg(i: number): string { return i === this.sel ? 'var(--surface-raised)' : 'transparent'; }
  rowBorder(i: number): string { return i === this.sel ? 'var(--accent)' : 'transparent'; }
  dimOpacity(i: number): string { return this.done[i] ? '0.55' : '1'; }
  statusLabel(i: number): string { return this.done[i] ? this.label(this.done[i]) : 'Pending'; }
  statusColor(i: number): string {
    const d = this.done[i];
    if (!d) return 'var(--text-faint)';
    return d === 'halt' ? 'var(--red-400)' : d === 'clear' ? 'var(--status-online)' : 'var(--accent)';
  }
  riskBg(r: number): string { return r >= 70 ? 'var(--status-danger)' : 'var(--surface-raised)'; }
  riskColor(r: number): string { return r >= 70 ? 'var(--white)' : 'var(--text-muted)'; }

  // ── detail helpers ──
  get pending(): number { return this.q.filter((_, i) => !this.done[i]).length; }
  get cur(): QueueItem { return this.q[this.sel]; }
  get curDone(): Resolution | undefined { return this.done[this.sel]; }
  get curVerdictColor(): string {
    return this.cur.verdict === 'Watch' || this.cur.verdict === 'Manual'
      ? 'var(--text-muted)'
      : 'var(--status-danger)';
  }
  get curRiskColor(): string { return this.cur.risk >= 70 ? 'var(--red-400)' : 'var(--text)'; }
  get curRiskBand(): string {
    return this.cur.risk >= 70 ? 'Critical' : this.cur.risk >= 30 ? 'Elevated' : 'Low';
  }
  get resolvedNote(): string {
    return this.curDone
      ? `This scan was ${this.label(this.curDone).toLowerCase()} and written to the audit log.`
      : '';
  }
}
