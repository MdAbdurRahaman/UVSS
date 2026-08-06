import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Subscription } from 'rxjs';

type SiteStatus = 'scanning' | 'idle' | 'offline';

interface Site {
  id: string;
  name: string;
  status: SiteStatus;
  scan: string;
  plate: string;
  risk: number;
  band: string;
  verdict: string;
  speed: string;
  scansToday: number;
  avgRisk: number | string;
  alerts: number;
  tunnel: 'Up' | 'Down';
  lastSync: string;
}

@Component({
  selector: 'app-central-site-live',
  templateUrl: './site-live.component.html',
  styleUrls: ['./site-live.component.css'],
})
export class SiteLiveComponent implements OnInit, OnDestroy {
  private sub?: Subscription;
  cur!: Site;

  private readonly sites: Record<string, Site> = {
    '01': { id: '01', name: 'BNS Issa Khan', status: 'scanning', scan: '#A-2291', plate: 'DL 3C AD 8491', risk: 84, band: 'Critical', verdict: 'Blacklist', speed: '4.2 km/h', scansToday: 312, avgRisk: 31, alerts: 2, tunnel: 'Up', lastSync: 'now' },
    '02': { id: '02', name: 'Chattogram Port', status: 'idle', scan: '—', plate: '—', risk: 0, band: 'Low', verdict: '—', speed: '0 km/h', scansToday: 188, avgRisk: 18, alerts: 0, tunnel: 'Up', lastSync: '12s ago' },
    '03': { id: '03', name: 'Mongla Port', status: 'scanning', scan: '#C-0884', plate: 'DHA GA 09-7733', risk: 71, band: 'Critical', verdict: 'Blacklist', speed: '3.6 km/h', scansToday: 241, avgRisk: 24, alerts: 1, tunnel: 'Up', lastSync: 'now' },
    '04': { id: '04', name: 'Payra Port', status: 'offline', scan: '—', plate: '—', risk: 0, band: '—', verdict: '—', speed: '—', scansToday: 96, avgRisk: '—', alerts: 0, tunnel: 'Down', lastSync: '11m ago' },
    '05': { id: '05', name: 'Benapole Port', status: 'idle', scan: '—', plate: '—', risk: 0, band: 'Low', verdict: '—', speed: '0 km/h', scansToday: 203, avgRisk: 20, alerts: 0, tunnel: 'Up', lastSync: '8s ago' },
    '06': { id: '06', name: 'Teknaf Port', status: 'idle', scan: '—', plate: '—', risk: 0, band: 'Low', verdict: '—', speed: '0 km/h', scansToday: 140, avgRisk: 22, alerts: 0, tunnel: 'Up', lastSync: '20s ago' },
  };

  constructor(private route: ActivatedRoute) {}

  ngOnInit(): void {
    this.sub = this.route.paramMap.subscribe((p) => {
      const id = p.get('id') ?? '01';
      this.cur = this.sites[id] ?? this.sites['01'];
    });
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  // Colors resolve through the design-system tokens so they follow the theme.
  get statusColor(): string {
    return this.cur.status === 'scanning'
      ? 'var(--status-online)'
      : this.cur.status === 'idle'
        ? 'var(--status-idle)'
        : 'var(--status-danger)';
  }
  get statusLabel(): string {
    return this.cur.status === 'scanning' ? 'Scanning' : this.cur.status === 'idle' ? 'Idle' : 'Offline';
  }
  get riskColor(): string {
    return this.cur.risk >= 70
      ? 'var(--red-400)'
      : this.cur.risk >= 30
        ? 'var(--accent)'
        : 'var(--text-muted)';
  }
}
