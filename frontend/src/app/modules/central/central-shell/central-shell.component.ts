import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from 'src/app/core/services/auth.service';
import { ThemeService } from 'src/app/core/services/theme.service';

@Component({
  selector: 'app-central-shell',
  templateUrl: './central-shell.component.html',
  styleUrls: ['./central-shell.component.css'],
})
export class CentralShellComponent {
  constructor(
    private auth: AuthService,
    private router: Router,
    public theme: ThemeService,
  ) {}

  logout(): void {
    this.auth.logout('central');
    this.router.navigate(['/central/login']);
  }
}
