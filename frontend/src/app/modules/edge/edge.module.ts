import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';

import { SharedModule } from 'src/app/shared/shared.module';
import { EdgeRoutingModule } from './edge-routing.module';
import { EdgeShellComponent } from './edge-shell/edge-shell.component';
import { ConsoleComponent } from './console/console.component';
import { HistoryComponent } from './history/history.component';
import { AlertsComponent } from './alerts/alerts.component';
import { BlacklistComponent } from './blacklist/blacklist.component';
import { ReportsComponent } from './reports/reports.component';
import { SystemComponent } from './system/system.component';
import { DriverFaceComponent } from './driver-face/driver-face.component';

@NgModule({
  declarations: [
    EdgeShellComponent,
    ConsoleComponent,
    HistoryComponent,
    AlertsComponent,
    BlacklistComponent,
    ReportsComponent,
    SystemComponent,
    DriverFaceComponent,
  ],
  imports: [CommonModule, FormsModule, RouterModule, SharedModule, EdgeRoutingModule],
})
export class EdgeModule {}
