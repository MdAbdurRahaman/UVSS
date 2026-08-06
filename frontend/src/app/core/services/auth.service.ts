import { Injectable, Inject, PLATFORM_ID } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';

/** The two independently-authenticated dashboards. */
export type Dashboard = 'edge' | 'central';

/**
 * Client-side mock auth — no backend yet.
 *
 * Two INDEPENDENT sessions: signing into the Edge console does not grant the
 * Central command (and vice-versa). Each dashboard keeps its own flag in
 * localStorage. Shared demo credentials for both:
 *   username: dubotech   password: dubotech   2FA code: 123456
 *
 * Flow mirrors the UVSS Sign In design: credentials step → OTP step.
 * All storage access is guarded for SSR (server has no localStorage).
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private static readonly USERNAME = 'dubotech';
  private static readonly PASSWORD = 'dubotech';
  private static readonly OTP = '123456';

  private readonly isBrowser: boolean;

  /** Username captured at the credentials step, awaiting OTP — per dashboard. */
  private pendingUser: Record<Dashboard, string | null> = { edge: null, central: null };

  constructor(@Inject(PLATFORM_ID) platformId: Object) {
    this.isBrowser = isPlatformBrowser(platformId);
  }

  private storeKey(d: Dashboard): string { return `uvss-auth-${d}`; }
  private userKey(d: Dashboard): string { return `uvss-user-${d}`; }

  /** Step 1 — validate username + password for the given dashboard. */
  verifyCredentials(dashboard: Dashboard, username: string, password: string): boolean {
    const ok =
      username.trim().toLowerCase() === AuthService.USERNAME &&
      password === AuthService.PASSWORD;
    this.pendingUser[dashboard] = ok ? username.trim() : null;
    return ok;
  }

  /** Step 2 — validate the 6-digit OTP and complete sign-in for the dashboard. */
  verifyOtp(dashboard: Dashboard, code: string): boolean {
    if (!this.pendingUser[dashboard]) return false;
    if (code.trim() !== AuthService.OTP) return false;
    if (this.isBrowser) {
      localStorage.setItem(this.storeKey(dashboard), 'true');
      localStorage.setItem(this.userKey(dashboard), this.pendingUser[dashboard] as string);
    }
    this.pendingUser[dashboard] = null;
    return true;
  }

  isLoggedIn(dashboard: Dashboard): boolean {
    if (!this.isBrowser) return false;
    return localStorage.getItem(this.storeKey(dashboard)) === 'true';
  }

  username(dashboard: Dashboard): string {
    if (!this.isBrowser) return 'operator';
    return localStorage.getItem(this.userKey(dashboard)) || 'operator';
  }

  logout(dashboard: Dashboard): void {
    if (this.isBrowser) {
      localStorage.removeItem(this.storeKey(dashboard));
      localStorage.removeItem(this.userKey(dashboard));
    }
    this.pendingUser[dashboard] = null;
  }
}
