import 'zone.js/node';
import { APP_BASE_HREF } from '@angular/common';
import { renderModule } from '@angular/platform-server';
import { AppServerModule } from './src/app/app.server.module';
import express from 'express';
import { readFileSync } from 'fs';
import { join } from 'path';

const app = express();
const PORT = process.env['PORT'] || 4000;
const browserDist = join(process.cwd(), 'dist', 'frontend');
const indexHtml = readFileSync(join(browserDist, 'index.html'), 'utf-8');

// Static assets (hashed bundles, images, fonts)
app.get('*.*', express.static(browserDist, { maxAge: '1y' }));

// All routes rendered by Angular SSR
app.get('*', async (req: express.Request, res: express.Response) => {
  try {
    const html = await renderModule(AppServerModule, {
      document: indexHtml,
      url: req.url,
      extraProviders: [{ provide: APP_BASE_HREF, useValue: req.baseUrl }],
    });
    res.send(html);
  } catch (err) {
    console.error('SSR render error:', err);
    res.send(indexHtml);
  }
});

app.listen(PORT, () => {
  console.log(`UVSS SSR server running on http://localhost:${PORT}`);
});
