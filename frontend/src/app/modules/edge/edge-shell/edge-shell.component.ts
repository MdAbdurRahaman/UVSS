import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from 'src/app/core/services/auth.service';
import { ThemeService } from 'src/app/core/services/theme.service';

@Component({
  selector: 'app-edge-shell',
  templateUrl: './edge-shell.component.html',
  styleUrls: ['./edge-shell.component.css'],
})
export class EdgeShellComponent {
  constructor(
    private auth: AuthService,
    private router: Router,
    public theme: ThemeService,
  ) {}

  /** The live-scan banner in the top bar is a console-screen affordance. */
  get onConsole(): boolean {
    return this.router.url.startsWith('/edge/console');
  }

  logout(): void {
    this.auth.logout('edge');
    this.router.navigate(['/edge/login']);
  }
}
