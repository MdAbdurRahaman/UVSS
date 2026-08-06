import { Component } from '@angular/core';

export type Health = 'healthy' | 'degraded' | 'offline';

export interface SystemItem {
  label: string;
  desc: string;
  /** Whether the operator has this component enabled. */
  on: boolean;
  health: Health;
  /** Rolling availability, percent. */
  uptime: number;
  /** Seconds since the last successful health probe. */
  lastCheck: number;
  /** Free-form reading shown next to the status — load, signal, latency. */
  metric: string;
  /** Populated when health is not 'healthy'. */
  note: string;
}

export interface SystemGroup {
  title: string;
  icon: string;
  items: SystemItem[];
}

@Component({
  selector: 'app-edge-system',
  templateUrl: './system.component.html',
  styleUrls: ['./system.component.css'],
})
export class SystemComponent {
  /** Set while a manual health check is in flight. */
  checking = false;

  groups: SystemGroup[] = [
    {
      title: 'Capture',
      icon: 'fa-camera',
      items: [
        { label: 'Stitched composite', desc: 'Line-scan undercarriage stitch', on: true, health: 'healthy', uptime: 99.8, lastCheck: 2, metric: '60 fps · 4096 px', note: '' },
        { label: '3D stereo', desc: 'Dual-sensor red/cyan anaglyph depth', on: true, health: 'healthy', uptime: 99.4, lastCheck: 2, metric: 'pair sync 0.4 ms', note: '' },
        { label: 'Side cameras', desc: 'Left + right chassis view', on: true, health: 'healthy', uptime: 99.9, lastCheck: 3, metric: '2 × 1080p', note: '' },
        { label: 'ANPR front', desc: 'Front plate capture', on: true, health: 'healthy', uptime: 99.1, lastCheck: 1, metric: 'read 98.6%', note: '' },
        { label: 'ANPR rear', desc: 'Rear plate capture', on: true, health: 'degraded', uptime: 91.2, lastCheck: 4, metric: 'read 88.3%', note: 'Lens contamination suspected — read rate below 95% threshold.' },
        { label: 'Live entry video', desc: 'Entry-lane camera feed', on: true, health: 'healthy', uptime: 99.7, lastCheck: 2, metric: '1080p · 30 fps', note: '' },
      ],
    },
    {
      title: 'Sensors & triggers',
      icon: 'fa-tower-broadcast',
      items: [
        { label: 'Inductive loop', desc: 'Vehicle-present detector', on: true, health: 'healthy', uptime: 100, lastCheck: 1, metric: 'idle', note: '' },
        { label: 'IR trigger', desc: 'Arms the scan on break-beam', on: true, health: 'healthy', uptime: 99.9, lastCheck: 1, metric: 'beam OK', note: '' },
        { label: 'Doppler radar', desc: 'Speed measurement', on: true, health: 'healthy', uptime: 99.6, lastCheck: 3, metric: '4.2 km/h', note: '' },
        { label: 'LED line bars', desc: 'Scan illumination', on: true, health: 'degraded', uptime: 96.4, lastCheck: 5, metric: '2 of 24 dead', note: 'Two emitters out on the left bar — brightness compensated in software.' },
      ],
    },
    {
      title: 'Compute & AI',
      icon: 'fa-microchip',
      items: [
        { label: 'Threat detection', desc: 'Foreign-object model', on: true, health: 'healthy', uptime: 99.5, lastCheck: 2, metric: 'GPU 61% · 38 ms', note: '' },
        { label: 'Anomaly detection', desc: 'Undercarriage anomaly model', on: true, health: 'healthy', uptime: 99.5, lastCheck: 2, metric: 'GPU 22% · 24 ms', note: '' },
        { label: 'Baseline difference', desc: 'Compare against the clean baseline', on: false, health: 'offline', uptime: 0, lastCheck: 0, metric: 'disabled', note: 'Disabled by the operator — no baseline comparison is running.' },
        { label: 'Edge compute node', desc: 'Host CPU, memory and storage', on: true, health: 'healthy', uptime: 99.9, lastCheck: 1, metric: 'CPU 34% · RAM 47% · disk 62%', note: '' },
      ],
    },
    {
      title: 'Connectivity & storage',
      icon: 'fa-network-wired',
      items: [
        { label: 'Encrypted tunnel to central', desc: 'mTLS uplink to Central command', on: true, health: 'healthy', uptime: 99.3, lastCheck: 1, metric: 'RTT 28 ms', note: '' },
        { label: 'Plate watchlist sync', desc: 'Match plates to the central watchlist', on: true, health: 'healthy', uptime: 99.2, lastCheck: 6, metric: 'synced 14:31', note: '' },
        { label: 'Auto-upload flagged scans', desc: 'Push halted scans to central', on: true, health: 'degraded', uptime: 94.8, lastCheck: 8, metric: '3 queued', note: 'Upload queue backing up — retrying with exponential backoff.' },
        { label: 'Local scan archive', desc: 'On-disk retention of scan records', on: true, health: 'healthy', uptime: 100, lastCheck: 4, metric: '62% of 4 TB · 31 d', note: '' },
      ],
    },
  ];

  private get all(): SystemItem[] {
    return this.groups.reduce<SystemItem[]>((acc, g) => acc.concat(g.items), []);
  }

  get totalCount(): number { return this.all.length; }
  get healthyCount(): number { return this.all.filter((i) => i.health === 'healthy').length; }
  get degradedCount(): number { return this.all.filter((i) => i.health === 'degraded').length; }
  get offlineCount(): number { return this.all.filter((i) => i.health === 'offline').length; }
  get enabledCount(): number { return this.all.filter((i) => i.on).length; }

  /** Worst health across the whole edge — drives the header chip. */
  get overall(): Health {
    if (this.offlineCount) return 'offline';
    if (this.degradedCount) return 'degraded';
    return 'healthy';
  }

  overallLabel(): string {
    if (this.overall === 'offline') return 'Attention required';
    if (this.overall === 'degraded') return 'Degraded';
    return 'All systems healthy';
  }

  /** Turning a component off reports it as offline rather than faking a probe. */
  toggle(item: SystemItem): void {
    item.on = !item.on;
    if (!item.on) {
      item.health = 'offline';
      item.metric = 'disabled';
      item.note = 'Disabled by the operator.';
      item.uptime = 0;
    } else {
      item.health = 'healthy';
      item.metric = 'starting…';
      item.note = '';
      item.uptime = 100;
      item.lastCheck = 0;
    }
  }

  /** Re-probe every enabled component. */
  runCheck(): void {
    if (this.checking) return;
    this.checking = true;
    setTimeout(() => {
      this.all.filter((i) => i.on).forEach((i) => (i.lastCheck = 0));
      this.checking = false;
    }, 900);
  }

  statusColor(h: Health): string {
    if (h === 'healthy') return 'var(--status-online)';
    if (h === 'degraded') return 'var(--status-warn)';
    return 'var(--status-danger)';
  }

  statusText(h: Health): string {
    if (h === 'healthy') return 'var(--green-400)';
    if (h === 'degraded') return 'var(--yellow-500)';
    return 'var(--red-400)';
  }

  statusIcon(h: Health): string {
    if (h === 'healthy') return 'fa-circle-check';
    if (h === 'degraded') return 'fa-triangle-exclamation';
    return 'fa-circle-xmark';
  }

  statusLabel(h: Health): string {
    if (h === 'healthy') return 'Healthy';
    if (h === 'degraded') return 'Degraded';
    return 'Offline';
  }

  lastCheckLabel(i: SystemItem): string {
    if (!i.on) return '—';
    return i.lastCheck === 0 ? 'just now' : i.lastCheck + 's ago';
  }
}
