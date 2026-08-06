import { Injectable, Inject, PLATFORM_ID } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';

export type BlacklistSeverity = 'High' | 'Medium' | 'Low';

export const BLACKLIST_SEVERITIES: BlacklistSeverity[] = ['High', 'Medium', 'Low'];

export const BLACKLIST_REASONS = [
  'Stolen vehicle',
  'Wanted / BOLO',
  'Expired permit',
  'Repeat threat detection',
  'Access revoked',
  'Other',
];

export interface BlacklistEntry {
  id: string;
  /** Stored normalised: uppercase, single-spaced. */
  plate: string;
  reason: string;
  severity: BlacklistSeverity;
  notes: string;
  addedBy: string;
  /** ISO string — rendered with the date pipe. */
  addedAt: string;
  active: boolean;
}

const STORE_KEY = 'uvss-blacklist';

const SEED: BlacklistEntry[] = [
  { id: 'b1', plate: 'DL 3C AD 8491', reason: 'Wanted / BOLO', severity: 'High', notes: 'Flagged by Central watchlist sync.', addedBy: 'S. Karim', addedAt: '2026-06-18T09:12:00.000Z', active: true },
  { id: 'b2', plate: 'DHA GA 09-7733', reason: 'Repeat threat detection', severity: 'High', notes: 'Three foreign-object hits in 30 days.', addedBy: 'R. Ahmed', addedAt: '2026-06-21T14:40:00.000Z', active: true },
  { id: 'b3', plate: 'CTG HA 21-4410', reason: 'Expired permit', severity: 'Medium', notes: '', addedBy: 'R. Ahmed', addedAt: '2026-06-24T07:55:00.000Z', active: false },
];

/**
 * Number-plate blacklist store.
 *
 * Mock/local-only, same shape as AlertPolicyService: in-memory state mirrored
 * to localStorage, all storage access SSR-guarded.
 */
@Injectable({ providedIn: 'root' })
export class BlacklistService {
  private readonly isBrowser: boolean;

  entries: BlacklistEntry[] = [];
  private seq = 100;

  constructor(@Inject(PLATFORM_ID) platformId: Object) {
    this.isBrowser = isPlatformBrowser(platformId);
    this.entries = this.read();
  }

  /** Uppercase, collapse whitespace — so "dl 3c  ad 8491" matches "DL 3C AD 8491". */
  static normalise(plate: string): string {
    return plate.trim().toUpperCase().replace(/\s+/g, ' ');
  }

  has(plate: string): boolean {
    const p = BlacklistService.normalise(plate);
    return this.entries.some((e) => e.plate === p);
  }

  add(input: {
    plate: string;
    reason: string;
    severity: BlacklistSeverity;
    notes: string;
    addedBy: string;
    addedAt: string;
  }): BlacklistEntry {
    const created: BlacklistEntry = {
      id: `b${this.seq++}`,
      plate: BlacklistService.normalise(input.plate),
      reason: input.reason,
      severity: input.severity,
      notes: input.notes.trim(),
      addedBy: input.addedBy,
      addedAt: input.addedAt,
      active: true,
    };
    this.entries = [created, ...this.entries];
    this.write();
    return created;
  }

  remove(id: string): void {
    this.entries = this.entries.filter((e) => e.id !== id);
    this.write();
  }

  toggleActive(id: string): void {
    this.entries = this.entries.map((e) =>
      e.id === id ? { ...e, active: !e.active } : e,
    );
    this.write();
  }

  get activeCount(): number {
    return this.entries.filter((e) => e.active).length;
  }

  private read(): BlacklistEntry[] {
    if (!this.isBrowser) return [...SEED];
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return [...SEED];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? (parsed as BlacklistEntry[]) : [...SEED];
    } catch {
      return [...SEED];
    }
  }

  private write(): void {
    if (!this.isBrowser) return;
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(this.entries));
    } catch {
      /* quota or private-mode: state stays in memory for the session */
    }
  }
}
