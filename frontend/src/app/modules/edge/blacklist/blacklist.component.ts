import { Component } from '@angular/core';
import { AuthService } from 'src/app/core/services/auth.service';
import {
  BLACKLIST_REASONS,
  BLACKLIST_SEVERITIES,
  BlacklistEntry,
  BlacklistService,
  BlacklistSeverity,
} from 'src/app/core/services/blacklist.service';

@Component({
  selector: 'app-edge-blacklist',
  templateUrl: './blacklist.component.html',
  styleUrls: ['./blacklist.component.css'],
})
export class BlacklistComponent {
  readonly reasons = BLACKLIST_REASONS;
  readonly severities = BLACKLIST_SEVERITIES;

  /** Add-plate form. */
  plate = '';
  reason = BLACKLIST_REASONS[0];
  severity: BlacklistSeverity = 'High';
  notes = '';
  error = '';
  justAdded = '';

  /** Table filter. */
  query = '';

  constructor(
    private store: BlacklistService,
    private auth: AuthService,
  ) {}

  get entries(): BlacklistEntry[] {
    const q = this.query.trim().toUpperCase();
    if (!q) return this.store.entries;
    return this.store.entries.filter(
      (e) => e.plate.includes(q) || e.reason.toUpperCase().includes(q),
    );
  }

  get total(): number { return this.store.entries.length; }
  get activeCount(): number { return this.store.activeCount; }
  get highCount(): number {
    return this.store.entries.filter((e) => e.active && e.severity === 'High').length;
  }

  /** Live preview of how the plate will be stored. */
  get normalised(): string { return BlacklistService.normalise(this.plate); }

  add(): void {
    const plate = this.normalised;
    this.justAdded = '';

    if (plate.length < 4) { this.error = 'Enter a full number plate (min 4 characters).'; return; }
    if (!/^[A-Z0-9 \-]+$/.test(plate)) { this.error = 'Plate may only contain letters, digits, spaces and hyphens.'; return; }
    if (this.store.has(plate)) { this.error = plate + ' is already blacklisted.'; return; }

    this.store.add({
      plate,
      reason: this.reason,
      severity: this.severity,
      notes: this.notes,
      addedBy: this.auth.username('edge'),
      addedAt: new Date().toISOString(),
    });

    this.error = '';
    this.justAdded = plate;
    this.plate = '';
    this.notes = '';
  }

  remove(id: string): void { this.store.remove(id); }
  toggleActive(id: string): void { this.store.toggleActive(id); }

  /** Left border / dot colour for a row. */
  severityColor(s: BlacklistSeverity): string {
    if (s === 'High') return 'var(--status-danger)';
    if (s === 'Medium') return 'var(--status-warn)';
    return 'var(--gray-600)';
  }

  /** Text colour for the severity label. */
  severityText(s: BlacklistSeverity): string {
    if (s === 'High') return 'var(--red-400)';
    if (s === 'Medium') return 'var(--yellow-500)';
    return 'var(--text-muted)';
  }
}
