import { Injectable, Inject, PLATFORM_ID, signal } from '@angular/core';
import { isPlatformBrowser, DOCUMENT } from '@angular/common';

export type Theme = 'dark' | 'light';

/**
 * Dark/light switch for the Dubo OS design system.
 *
 * The system ships dark under `html.dark` and light under `html:not(.dark)`;
 * the token layer also honours `[data-theme="light"]`, so both hooks are
 * stamped together.
 *
 * The FIRST paint is not this service's job — `index.html` carries a blocking
 * script that reads the same localStorage key before Angular boots, so a
 * server-rendered page never flashes the wrong theme. This service only owns
 * runtime toggling and keeps `current` in sync for templates to bind against.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private static readonly KEY = 'uvss-theme';

  private readonly isBrowser: boolean;

  /** Reactive current theme — templates read this to pick the toggle icon. */
  readonly current = signal<Theme>('dark');

  constructor(
    @Inject(PLATFORM_ID) platformId: Object,
    @Inject(DOCUMENT) private doc: Document,
  ) {
    this.isBrowser = isPlatformBrowser(platformId);
    if (this.isBrowser) this.current.set(this.stored() ?? 'dark');
  }

  private stored(): Theme | null {
    try {
      return localStorage.getItem(ThemeService.KEY) === 'light' ? 'light' : 'dark';
    } catch {
      return null;
    }
  }

  /** Apply a theme and persist it. No-op on the server. */
  set(theme: Theme): void {
    this.current.set(theme);
    if (!this.isBrowser) return;

    const root = this.doc.documentElement;
    root.classList.toggle('dark', theme === 'dark');
    root.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(ThemeService.KEY, theme);
    } catch {
      /* storage blocked — the class change still applies for this session */
    }
  }

  toggle(): void {
    this.set(this.current() === 'dark' ? 'light' : 'dark');
  }

  /** Font Awesome glyph for the toggle button: sun while dark, moon while light. */
  get toggleIcon(): string {
    return this.current() === 'dark' ? 'fa-sun' : 'fa-moon';
  }

  get toggleLabel(): string {
    return this.current() === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
  }
}
