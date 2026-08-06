import { Component } from '@angular/core';

type ViewerTab = 'composite' | 'stereo' | 'live' | 'side';

interface Scan {
  id: string;
  time: string;
  tag: 'blacklist' | 'watch' | 'cleared';
  risk: number;
  verdict: string;
  plate: string;
  detections: number;
  threat: number;
  anomaly: number;
  baseline: number;
  watchlist: boolean;
}

@Component({
  selector: 'app-edge-console',
  templateUrl: './console.component.html',
  styleUrls: ['./console.component.css'],
})
export class ConsoleComponent {
  view: ViewerTab = 'composite';
  rotX = -6;
  rotY = 0;

  /** Today's scans — the first is the live one in the pit. */
  scans: Scan[] = [
    { id: '#A-2291', time: '14:32', tag: 'blacklist', risk: 84, verdict: 'Blacklist', plate: 'DL 3C AD 8491', detections: 3, threat: 0.91, anomaly: 0.58, baseline: 0.46, watchlist: true },
    { id: '#A-2290', time: '14:28', tag: 'cleared', risk: 12, verdict: 'Cleared', plate: 'DHA GA 41-1188', detections: 0, threat: 0.08, anomaly: 0.11, baseline: 0.05, watchlist: false },
    { id: '#A-2289', time: '14:21', tag: 'watch', risk: 28, verdict: 'Watch', plate: 'CTG HA 21-4410', detections: 1, threat: 0.22, anomaly: 0.18, baseline: 0.12, watchlist: false },
    { id: '#A-2288', time: '14:17', tag: 'cleared', risk: 7, verdict: 'Cleared', plate: 'DHA GHA 01-0044', detections: 0, threat: 0.05, anomaly: 0.04, baseline: 0.03, watchlist: false },
    { id: '#A-2287', time: '14:09', tag: 'cleared', risk: 19, verdict: 'Cleared', plate: 'RAJ KHA 33-9921', detections: 0, threat: 0.12, anomaly: 0.09, baseline: 0.07, watchlist: false },
  ];
  selected = 0;

  /** Thumbnail background offsets, kept per slot so the filmstrip stays varied. */
  readonly thumbPos = ['center', '30% 30%', '70% 60%', '20% 80%', '90% 20%'];

  select(i: number): void {
    this.selected = i;
  }

  get cur(): Scan {
    return this.scans[this.selected];
  }
  get isLive(): boolean {
    return this.selected === 0;
  }

  // ── risk helpers ──
  // Colors resolve through the design-system tokens so they follow the theme.
  riskColor(r: number): string {
    return r >= 70 ? 'var(--status-danger)' : r >= 30 ? 'var(--accent)' : 'var(--text-muted)';
  }
  riskBand(r: number): string {
    return r >= 70 ? 'Critical' : r >= 30 ? 'Elevated' : 'Low';
  }
  riskAdvice(r: number): string {
    return r >= 70 ? '/ 100 · Halt recommended' : r >= 30 ? '/ 100 · Review advised' : '/ 100 · Clear to pass';
  }
  pct(v: number): number {
    return Math.round(v * 100);
  }

  // ── filmstrip helpers ──
  thumbBg(i: number): string {
    return `url('assets/undercarriage.jpg') ${this.thumbPos[i]}/180% no-repeat`;
  }
  badgeBg(s: Scan): string {
    return s.risk >= 70 ? 'var(--status-danger)' : 'var(--surface-raised)';
  }
  badgeColor(s: Scan): string {
    return s.risk >= 70 ? 'var(--white)' : 'var(--text-muted)';
  }
  tagLabel(s: Scan): string {
    return s.tag;
  }

  // ── viewer tabs ──
  setView(v: ViewerTab): void {
    this.view = v;
  }
  tabBg(v: ViewerTab): string {
    return this.view === v ? 'var(--brand)' : 'transparent';
  }
  tabColor(v: ViewerTab): string {
    return this.view === v ? 'var(--white)' : 'var(--text-muted)';
  }

  get stereoTransform(): string {
    return `perspective(900px) rotateX(${this.rotX}deg) rotateY(${this.rotY}deg) scaleX(-1)`;
  }

  stereoDown(event: MouseEvent): void {
    event.preventDefault();
    const start = { px: event.clientX, py: event.clientY, rx: this.rotX, ry: this.rotY };
    const move = (ev: MouseEvent) => {
      const dx = ev.clientX - start.px;
      const dy = ev.clientY - start.py;
      this.rotY = start.ry + dx * 0.45;
      this.rotX = Math.max(-35, Math.min(35, start.rx - dy * 0.45));
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  }
}
