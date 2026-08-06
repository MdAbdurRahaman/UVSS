import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { LandingComponent } from './landing/landing.component';

const routes: Routes = [
  { path: '', component: LandingComponent },
  {
    path: 'edge',
    loadChildren: () =>
      import('./modules/edge/edge.module').then((m) => m.EdgeModule),
  },
  {
    path: 'central',
    loadChildren: () =>
      import('./modules/central/central.module').then((m) => m.CentralModule),
  },
  { path: '**', redirectTo: '' },
];

@NgModule({
  imports: [
    RouterModule.forRoot(routes, {
      scrollPositionRestoration: 'enabled',
    }),
  ],
  exports: [RouterModule],
})
export class AppRoutingModule {}
