import { Component } from '@angular/core';

interface RecentReport {
  title: string;
  meta: string;
  time: string;
  fmt: string;
}

@Component({
  selector: 'app-central-reports',
  templateUrl: './reports.component.html',
  styleUrls: ['./reports.component.css'],
})
export class ReportsComponent {
  type = 0;
  range = 0;
  format = 0;

  readonly types = ['Daily throughput', 'Watchlist hits', 'Uptime & sync'];
  readonly ranges = ['Today', 'Last 7 days', 'Last 30 days'];
  readonly formats = ['PDF', 'CSV'];

  recent: RecentReport[] = [
    { title: 'Daily throughput', meta: 'Today · PDF', time: '06:00', fmt: 'PDF' },
    { title: 'Watchlist hits', meta: 'Last 7 days · CSV', time: 'Mon 08:00', fmt: 'CSV' },
  ];

  readonly scheds = [
    { label: 'Daily throughput', meta: 'PDF · 06:00 · all sites', freq: 'Daily' },
    { label: 'Watchlist hits', meta: 'CSV · Mon 08:00', freq: 'Weekly' },
    { label: 'Uptime & sync', meta: 'PDF · 1st of month', freq: 'Monthly' },
  ];
  schedOn = [true, true, false];

  generate(): void {
    this.recent.unshift({
      title: this.types[this.type],
      meta: `${this.ranges[this.range]} · ${this.formats[this.format]}`,
      time: 'just now',
      fmt: this.formats[this.format],
    });
  }
}
