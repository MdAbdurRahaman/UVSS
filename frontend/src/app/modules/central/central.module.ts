import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';

import { SharedModule } from 'src/app/shared/shared.module';
import { CentralRoutingModule } from './central-routing.module';
import { CentralShellComponent } from './central-shell/central-shell.component';
import { CommandComponent } from './command/command.component';
import { SitesComponent } from './sites/sites.component';
import { WatchlistComponent } from './watchlist/watchlist.component';
import { CentralAlertsComponent } from './alerts/alerts.component';
import { ReportsComponent } from './reports/reports.component';
import { ReviewComponent } from './review/review.component';
import { SearchComponent } from './search/search.component';
import { SiteLiveComponent } from './site-live/site-live.component';

@NgModule({
  declarations: [
    CentralShellComponent,
    CommandComponent,
    SitesComponent,
    WatchlistComponent,
    CentralAlertsComponent,
    ReportsComponent,
    ReviewComponent,
    SearchComponent,
    SiteLiveComponent,
  ],
  imports: [CommonModule, FormsModule, RouterModule, SharedModule, CentralRoutingModule],
})
export class CentralModule {}
