import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AuthGuard } from 'src/app/core/guards/auth.guard';
import { SignInComponent } from 'src/app/shared/sign-in/sign-in.component';
import { CentralShellComponent } from './central-shell/central-shell.component';
import { CommandComponent } from './command/command.component';
import { SitesComponent } from './sites/sites.component';
import { WatchlistComponent } from './watchlist/watchlist.component';
import { CentralAlertsComponent } from './alerts/alerts.component';
import { ReportsComponent } from './reports/reports.component';
import { ReviewComponent } from './review/review.component';
import { SearchComponent } from './search/search.component';
import { SiteLiveComponent } from './site-live/site-live.component';

const routes: Routes = [
  { path: 'login', component: SignInComponent, data: { dashboard: 'central' } },
  {
    path: '',
    component: CentralShellComponent,
    canActivate: [AuthGuard],
    data: { dashboard: 'central' },
    children: [
      { path: '', redirectTo: 'command', pathMatch: 'full' },
      { path: 'command', component: CommandComponent },
      { path: 'sites', component: SitesComponent },
      { path: 'site/:id', component: SiteLiveComponent },
      { path: 'watchlist', component: WatchlistComponent },
      { path: 'alerts', component: CentralAlertsComponent },
      { path: 'reports', component: ReportsComponent },
      { path: 'review', component: ReviewComponent },
      { path: 'search', component: SearchComponent },
    ],
  },
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule],
})
export class CentralRoutingModule {}
