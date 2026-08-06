import { Component, ElementRef, QueryList, ViewChildren } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService, Dashboard } from 'src/app/core/services/auth.service';
import { ThemeService } from 'src/app/core/services/theme.service';

@Component({
  selector: 'app-sign-in',
  templateUrl: './sign-in.component.html',
  styleUrls: ['./sign-in.component.css'],
})
export class SignInComponent {
  /** Which dashboard this login gates — from route data. */
  dashboard: Dashboard = 'central';

  step: 'creds' | 'otp' = 'creds';
  username = '';
  password = '';
  otp: string[] = ['', '', '', '', '', ''];
  error = '';

  @ViewChildren('otpBox') otpBoxes!: QueryList<ElementRef<HTMLInputElement>>;

  constructor(
    private auth: AuthService,
    private router: Router,
    route: ActivatedRoute,
    public theme: ThemeService,
  ) {
    this.dashboard = (route.snapshot.data['dashboard'] as Dashboard) ?? 'central';
  }

  get dashLabel(): string {
    return this.dashboard === 'edge' ? 'Edge console' : 'Central command';
  }
  get dashBlurb(): string {
    return this.dashboard === 'edge'
      ? 'Site operator access — live capture, AI threat assist and the halt/pass call, on the edge.'
      : 'Multi-site command — fleet overview, alerts, watchlist and analyst review over an encrypted tunnel.';
  }
  private get homeRoute(): string {
    return this.dashboard === 'edge' ? '/edge/console' : '/central/command';
  }

  trackByIndex(i: number): number {
    return i;
  }

  toOtp(): void {
    this.error = '';
    if (this.auth.verifyCredentials(this.dashboard, this.username, this.password)) {
      this.step = 'otp';
    } else {
      this.error = 'Invalid username or password.';
    }
  }

  back(): void {
    this.step = 'creds';
    this.error = '';
    this.otp = ['', '', '', '', '', ''];
    this.otpBoxes?.forEach((b) => (b.nativeElement.value = ''));
  }

  onOtpInput(event: Event, i: number): void {
    const input = event.target as HTMLInputElement;
    const v = (input.value || '').replace(/\D/g, '').slice(-1);
    this.otp[i] = v;
    input.value = v;
    if (v && i < 5) {
      this.otpBoxes.get(i + 1)?.nativeElement.focus();
    }
  }

  onOtpKeydown(event: KeyboardEvent, i: number): void {
    if (event.key === 'Backspace' && !this.otp[i] && i > 0) {
      const prev = this.otpBoxes.get(i - 1)?.nativeElement;
      if (prev) {
        prev.focus();
        prev.value = '';
        this.otp[i - 1] = '';
      }
    }
  }

  onOtpPaste(event: ClipboardEvent): void {
    const text = (event.clipboardData?.getData('text') || '').replace(/\D/g, '').slice(0, 6);
    if (!text) return;
    event.preventDefault();
    const boxes = this.otpBoxes.toArray();
    for (let i = 0; i < 6; i++) {
      const ch = text[i] || '';
      this.otp[i] = ch;
      if (boxes[i]) boxes[i].nativeElement.value = ch;
    }
    boxes[Math.min(text.length, 5)]?.nativeElement.focus();
  }

  verify(): void {
    this.error = '';
    if (this.auth.verifyOtp(this.dashboard, this.otp.join(''))) {
      this.router.navigate([this.homeRoute]);
    } else {
      this.error = 'Incorrect code. Please try again.';
    }
  }
}
