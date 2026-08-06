import { Injectable, Inject, PLATFORM_ID } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';

/** The alert families a policy can route. */
export type AlertType = 'Blacklist' | 'Watch' | 'Tamper' | 'System';

export const ALERT_TYPES: AlertType[] = ['Blacklist', 'Watch', 'Tamper', 'System'];

/** A person who can be notified — name plus the two contact channels we dispatch on. */
export interface Recipient {
  id: string;
  name: string;
  email: string;
  phone: string;
  role: string;
}

/**
 * One routing rule: when an alert of `type` fires at or above `minRisk`,
 * notify `recipientIds` over the enabled channels.
 */
export interface AlertPolicy {
  id: string;
  type: AlertType;
  /** 0 means "any risk score". */
  minRisk: number;
  email: boolean;
  sms: boolean;
  recipientIds: string[];
  enabled: boolean;
}

const RECIPIENT_KEY = 'uvss-alert-recipients';
const POLICY_KEY = 'uvss-alert-policies';

const SEED_RECIPIENTS: Recipient[] = [
  { id: 'r1', name: 'R. Ahmed', email: 'r.ahmed@dubotech.com', phone: '+880 1711-000001', role: 'Lane operator' },
  { id: 'r2', name: 'S. Karim', email: 's.karim@dubotech.com', phone: '+880 1711-000002', role: 'Central analyst' },
  { id: 'r3', name: 'M. Hossain', email: 'm.hossain@dubotech.com', phone: '+880 1711-000003', role: 'Duty officer' },
];

const SEED_POLICIES: AlertPolicy[] = [
  { id: 'p1', type: 'Blacklist', minRisk: 70, email: true, sms: true, recipientIds: ['r1', 'r2', 'r3'], enabled: true },
  { id: 'p2', type: 'Watch', minRisk: 40, email: true, sms: false, recipientIds: ['r2'], enabled: true },
  { id: 'p3', type: 'Tamper', minRisk: 0, email: true, sms: true, recipientIds: ['r1'], enabled: true },
  { id: 'p4', type: 'System', minRisk: 0, email: true, sms: false, recipientIds: ['r3'], enabled: false },
];

/**
 * Notification policy store — who gets told about what.
 *
 * Mock/local-only like AuthService: state lives in memory and is mirrored to
 * localStorage so edits survive a reload. All storage access is SSR-guarded.
 */
@Injectable({ providedIn: 'root' })
export class AlertPolicyService {
  private readonly isBrowser: boolean;

  recipients: Recipient[] = [];
  policies: AlertPolicy[] = [];

  private seq = 100;

  constructor(@Inject(PLATFORM_ID) platformId: Object) {
    this.isBrowser = isPlatformBrowser(platformId);
    this.recipients = this.read<Recipient>(RECIPIENT_KEY, SEED_RECIPIENTS);
    this.policies = this.read<AlertPolicy>(POLICY_KEY, SEED_POLICIES);
  }

  // ── recipients ──────────────────────────────────────────────────────────
  addRecipient(r: Omit<Recipient, 'id'>): Recipient {
    const created: Recipient = { ...r, id: `r${this.seq++}` };
    this.recipients = [...this.recipients, created];
    this.write(RECIPIENT_KEY, this.recipients);
    return created;
  }

  removeRecipient(id: string): void {
    this.recipients = this.recipients.filter((r) => r.id !== id);
    // Drop the dangling reference from every rule that pointed at them.
    this.policies = this.policies.map((p) => ({
      ...p,
      recipientIds: p.recipientIds.filter((rid) => rid !== id),
    }));
    this.write(RECIPIENT_KEY, this.recipients);
    this.write(POLICY_KEY, this.policies);
  }

  recipient(id: string): Recipient | undefined {
    return this.recipients.find((r) => r.id === id);
  }

  recipientsFor(p: AlertPolicy): Recipient[] {
    return p.recipientIds
      .map((id) => this.recipient(id))
      .filter((r): r is Recipient => !!r);
  }

  /** True when this email is already on the list — used to block duplicates. */
  hasEmail(email: string): boolean {
    const e = email.trim().toLowerCase();
    return this.recipients.some((r) => r.email.toLowerCase() === e);
  }

  // ── policies ────────────────────────────────────────────────────────────
  addPolicy(p: Omit<AlertPolicy, 'id'>): AlertPolicy {
    const created: AlertPolicy = { ...p, id: `p${this.seq++}` };
    this.policies = [...this.policies, created];
    this.write(POLICY_KEY, this.policies);
    return created;
  }

  removePolicy(id: string): void {
    this.policies = this.policies.filter((p) => p.id !== id);
    this.write(POLICY_KEY, this.policies);
  }

  togglePolicy(id: string): void {
    this.policies = this.policies.map((p) =>
      p.id === id ? { ...p, enabled: !p.enabled } : p,
    );
    this.write(POLICY_KEY, this.policies);
  }

  /** Add/remove a recipient on an existing rule. */
  toggleRecipientOnPolicy(policyId: string, recipientId: string): void {
    this.policies = this.policies.map((p) => {
      if (p.id !== policyId) return p;
      const has = p.recipientIds.includes(recipientId);
      return {
        ...p,
        recipientIds: has
          ? p.recipientIds.filter((id) => id !== recipientId)
          : [...p.recipientIds, recipientId],
      };
    });
    this.write(POLICY_KEY, this.policies);
  }

  // ── persistence ─────────────────────────────────────────────────────────
  private read<T>(key: string, seed: T[]): T[] {
    if (!this.isBrowser) return [...seed];
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return [...seed];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? (parsed as T[]) : [...seed];
    } catch {
      return [...seed];
    }
  }

  private write(key: string, value: unknown): void {
    if (!this.isBrowser) return;
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* quota or private-mode: state stays in memory for the session */
    }
  }
}
