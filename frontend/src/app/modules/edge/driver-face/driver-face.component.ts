import { Component, Input } from '@angular/core';

export interface DriverFaceRecord {
  id: string;
  name: string;
  confidence: number;
  status: 'matched' | 'unidentified' | 'watchlist_flag';
  timestamp: string;
  imageUrl: string;
}

@Component({
  selector: 'app-driver-face',
  templateUrl: './driver-face.component.html',
  styleUrls: ['./driver-face.component.css']
})
export class DriverFaceComponent {
  @Input() driverFace: DriverFaceRecord = {
    id: 'DF-8842',
    name: 'R. Ahmed (Verified Driver)',
    confidence: 98.4,
    status: 'matched',
    timestamp: '14:32:08',
    imageUrl: 'assets/driver.jpg'
  };

  /** Recent face captures gallery */
  history: DriverFaceRecord[] = [
    {
      id: 'DF-8842',
      name: 'R. Ahmed',
      confidence: 98.4,
      status: 'matched',
      timestamp: '14:32:08',
      imageUrl: 'assets/driver.jpg'
    },
    {
      id: 'DF-8841',
      name: 'M. Hossain',
      confidence: 96.1,
      status: 'matched',
      timestamp: '14:28:15',
      imageUrl: 'assets/driver.jpg'
    },
    {
      id: 'DF-8840',
      name: 'Unidentified Driver',
      confidence: 62.3,
      status: 'unidentified',
      timestamp: '14:21:04',
      imageUrl: 'assets/driver.jpg'
    }
  ];

  selectedRecord: DriverFaceRecord = this.driverFace;

  selectRecord(record: DriverFaceRecord): void {
    this.selectedRecord = record;
  }
}
