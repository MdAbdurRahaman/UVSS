import { Injectable, Inject, PLATFORM_ID } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';
import { ActivatedRouteSnapshot, CanActivate, Router } from '@angular/router';
import { AuthService, Dashboard } from '../services/auth.service';

/**
 * Gates a dashboard's routes. The dashboard is read from the route's
 * `data.dashboard` ('edge' | 'central'); an unauthenticated visitor is sent to
 * that dashboard's own login. Skipped during SSR (the client re-checks).
 */
@Injectable({ providedIn: 'root' })
export class AuthGuard implements CanActivate {
  private readonly isBrowser: boolean;

  constructor(
    @Inject(PLATFORM_ID) platformId: Object,
    private auth: AuthService,
    private router: Router,
  ) {
    this.isBrowser = isPlatformBrowser(platformId);
  }

  canActivate(route: ActivatedRouteSnapshot): boolean {
    if (!this.isBrowser) return true;
    const dashboard = (route.data['dashboard'] as Dashboard) ?? 'central';
    if (this.auth.isLoggedIn(dashboard)) return true;
    this.router.navigate([`/${dashboard}/login`]);
    return false;
  }
}
