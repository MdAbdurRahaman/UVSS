import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AuthGuard } from 'src/app/core/guards/auth.guard';
import { SignInComponent } from 'src/app/shared/sign-in/sign-in.component';
import { EdgeShellComponent } from './edge-shell/edge-shell.component';
import { ConsoleComponent } from './console/console.component';
import { HistoryComponent } from './history/history.component';
import { AlertsComponent } from './alerts/alerts.component';
import { BlacklistComponent } from './blacklist/blacklist.component';
import { ReportsComponent } from './reports/reports.component';
import { SystemComponent } from './system/system.component';

const routes: Routes = [
  { path: 'login', component: SignInComponent, data: { dashboard: 'edge' } },
  {
    path: '',
    component: EdgeShellComponent,
    canActivate: [AuthGuard],
    data: { dashboard: 'edge' },
    children: [
      { path: '', redirectTo: 'console', pathMatch: 'full' },
      { path: 'console', component: ConsoleComponent },
      { path: 'history', component: HistoryComponent },
      { path: 'alerts', component: AlertsComponent },
      { path: 'blacklist', component: BlacklistComponent },
      { path: 'reports', component: ReportsComponent },
      { path: 'system', component: SystemComponent },
      // The setup screen became the system health page — keep old links working.
      { path: 'setup', redirectTo: 'system', pathMatch: 'full' },
    ],
  },
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule],
})
export class EdgeRoutingModule {}
