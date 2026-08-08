import { Component, Input, OnInit, OnDestroy } from '@angular/core';

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
export class DriverFaceComponent implements OnInit, OnDestroy {
  @Input() driverFace: DriverFaceRecord = {
    id: 'DF-8842',
    name: 'Live Driver Cam',
    confidence: 99.1,
    status: 'matched',
    timestamp: new Date().toLocaleTimeString(),
    imageUrl: 'http://localhost:8000/api/stream'
  };

  /** Control flag to turn Driver Face capture ON/OFF */
  isCaptureActive: boolean = true;

  /** Live MJPEG stream from Edge USB camera service */
  liveStreamUrl = 'http://localhost:8000/api/stream';
  private ws?: WebSocket;

  /** Recent face captures gallery (stores ONLY best face images per track) */
  history: DriverFaceRecord[] = [
    {
      id: 'DF-LIVE',
      name: 'USB Live Feed',
      confidence: 99.1,
      status: 'matched',
      timestamp: 'LIVE',
      imageUrl: 'http://localhost:8000/api/stream'
    },
    {
      id: 'DF-8842',
      name: 'Best Face - R. Ahmed',
      confidence: 98.4,
      status: 'matched',
      timestamp: '14:32:08',
      imageUrl: 'assets/driver.jpg'
    }
  ];

  selectedRecord: DriverFaceRecord = this.history[0];

  ngOnInit(): void {
    this.connectWebSocket();
  }

  ngOnDestroy(): void {
    if (this.ws) {
      this.ws.close();
    }
  }

  /** Turn Driver Face Capture ON or OFF */
  toggleCapture(): void {
    this.isCaptureActive = !this.isCaptureActive;
    if (this.isCaptureActive) {
      // Turn ON: start active edge capture session
      fetch('http://localhost:8000/api/session/start', { method: 'POST' }).catch(() => {});
      this.selectedRecord = this.history[0];
    } else {
      // Turn OFF: stop capture session
      fetch('http://localhost:8000/api/session/stop', { method: 'POST' }).catch(() => {});
    }
  }

  /** Storage folder information */
  savedFolderPath = '/home/lab-ros/Documents/mishu Uvss/dubotech_uvss-main/edge_deploy/sessions/';
  showStorageInfo = false;

  selectRecord(record: DriverFaceRecord): void {
    this.selectedRecord = record;
  }

  /** Open saved images folder on OS file manager & open web viewer */
  openSavedFiles(): void {
    this.showStorageInfo = !this.showStorageInfo;
    fetch('http://localhost:8000/api/open-folder', { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        if (data.path) {
          this.savedFolderPath = data.path;
        }
      })
      .catch(() => {});
  }

  openWebGallery(): void {
    window.open('http://localhost:8000/session-files/', '_blank');
  }

  private connectWebSocket(): void {
    try {
      this.ws = new WebSocket('ws://localhost:8000/ws');
      this.ws.onmessage = (event) => {
        if (!this.isCaptureActive) return;

        try {
          const data = JSON.parse(event.data);
          if (data.type === 'person' && data.person) {
            const p = data.person;
            // Keeps ONLY the single best face crop per subject
            const bestImage = p.images && p.images.length > 0 ? p.images[0] : null;
            const imageUrl = bestImage?.crop
              ? `http://localhost:8000${bestImage.crop}`
              : 'http://localhost:8000/api/stream';

            const newRecord: DriverFaceRecord = {
              id: `DF-${p.track_id}`,
              name: p.identity ? `Best Face (${p.identity})` : `Best Face (#${p.track_id})`,
              confidence: Math.round((p.best_score || 0.95) * 100),
              status: (p.best_score || 0.9) > 0.8 ? 'matched' : 'unidentified',
              timestamp: new Date().toLocaleTimeString(),
              imageUrl: imageUrl
            };

            // Update existing record if same track ID, or prepend single best face
            const existingIndex = this.history.findIndex(r => r.id === newRecord.id);
            if (existingIndex !== -1) {
              this.history[existingIndex] = newRecord;
            } else {
              this.history.unshift(newRecord);
              if (this.history.length > 6) {
                this.history.pop();
              }
            }
            this.selectedRecord = newRecord;
          }
        } catch (e) {
          // ignore
        }
      };
    } catch (e) {
      // ignore
    }
  }
}


