import { Component } from '@angular/core';
import {
  ALERT_TYPES,
  AlertPolicy,
  AlertPolicyService,
  AlertType,
  Recipient,
} from 'src/app/core/services/alert-policy.service';

type Tab = 'feed' | 'policy';

@Component({
  selector: 'app-edge-alerts',
  templateUrl: './alerts.component.html',
  styleUrls: ['./alerts.component.css'],
})
export class AlertsComponent {
  readonly alertTypes = ALERT_TYPES;

  tab: Tab = 'feed';

  /** New-recipient form. */
  rName = '';
  rEmail = '';
  rPhone = '';
  rRole = '';
  rError = '';

  /** New-policy form. */
  pType: AlertType = 'Blacklist';
  pMinRisk = 70;
  pEmail = true;
  pSms = false;
  pRecipients: string[] = [];
  pError = '';

  constructor(public store: AlertPolicyService) {}

  get recipients(): Recipient[] { return this.store.recipients; }
  get policies(): AlertPolicy[] { return this.store.policies; }

  // ── recipients ──────────────────────────────────────────────────────────
  addRecipient(): void {
    const name = this.rName.trim();
    const email = this.rEmail.trim();
    const phone = this.rPhone.trim();

    if (!name) { this.rError = 'Name is required.'; return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { this.rError = 'Enter a valid email address.'; return; }
    if (phone.replace(/\D/g, '').length < 7) { this.rError = 'Enter a valid phone number.'; return; }
    if (this.store.hasEmail(email)) { this.rError = 'That email is already on the list.'; return; }

    this.store.addRecipient({ name, email, phone, role: this.rRole.trim() || 'Operator' });
    this.rName = this.rEmail = this.rPhone = this.rRole = '';
    this.rError = '';
  }

  removeRecipient(id: string): void {
    this.store.removeRecipient(id);
    this.pRecipients = this.pRecipients.filter((r) => r !== id);
  }

  // ── policies ────────────────────────────────────────────────────────────
  /** Checkbox handler for the "who gets it" picker on the new-policy form. */
  togglePickedRecipient(id: string): void {
    this.pRecipients = this.pRecipients.includes(id)
      ? this.pRecipients.filter((r) => r !== id)
      : [...this.pRecipients, id];
  }

  isPicked(id: string): boolean { return this.pRecipients.includes(id); }

  addPolicy(): void {
    if (!this.pRecipients.length) { this.pError = 'Pick at least one recipient.'; return; }
    if (!this.pEmail && !this.pSms) { this.pError = 'Pick at least one channel.'; return; }

    this.store.addPolicy({
      type: this.pType,
      minRisk: Math.max(0, Math.min(100, Number(this.pMinRisk) || 0)),
      email: this.pEmail,
      sms: this.pSms,
      recipientIds: [...this.pRecipients],
      enabled: true,
    });
    this.pRecipients = [];
    this.pError = '';
  }

  removePolicy(id: string): void { this.store.removePolicy(id); }
  togglePolicy(id: string): void { this.store.togglePolicy(id); }
  toggleRecipientOnPolicy(pid: string, rid: string): void {
    this.store.toggleRecipientOnPolicy(pid, rid);
  }

  recipientsFor(p: AlertPolicy): Recipient[] { return this.store.recipientsFor(p); }

  channelLabel(p: AlertPolicy): string {
    const c = [p.email ? 'Email' : null, p.sms ? 'SMS' : null].filter(Boolean);
    return c.length ? c.join(' + ') : 'None';
  }

  riskLabel(p: AlertPolicy): string { return p.minRisk > 0 ? '≥ ' + p.minRisk : 'Any'; }

  typeColor(t: AlertType): string {
    if (t === 'Blacklist') return 'var(--red-400)';
    if (t === 'Tamper') return 'var(--accent)';
    return 'var(--text-muted)';
  }

  /** Rules currently switched on — shown as a summary chip in the header. */
  get activePolicyCount(): number {
    return this.policies.filter((p) => p.enabled).length;
  }
}
