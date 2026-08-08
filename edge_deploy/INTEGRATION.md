# Connecting the edge service to your existing website

A step-by-step guide. Assumes you already have a website and want to add the
live feed, the START/STOP control, and the detected-people results to it.

Nothing here requires you to change how your site is built or hosted.

---

## Table of contents

1. [How the pieces fit](#1-how-the-pieces-fit)
2. [Step 1 — start the service](#step-1--start-the-service)
3. [Step 2 — check it from your browser](#step-2--check-it-from-your-browser)
4. [Step 3 — add the client to your site](#step-3--add-the-client-to-your-site)
5. [Step 4 — the three integration points](#step-4--the-three-integration-points)
6. [Framework snippets](#framework-snippets)
7. [Triggering from ROS instead of a button](#triggering-from-ros-instead-of-a-button)
8. [Gotchas that will cost you an hour](#gotchas-that-will-cost-you-an-hour)
9. [Checklist](#checklist)

---

## 1. How the pieces fit

```
   YOUR WEBSITE                          EDGE COMPUTER
   (any host, any framework)             (runs edge_deploy/)

   <img src=".../api/stream">  ◄──────── MJPEG video
   uvss.on("person", …)        ◄──────── WebSocket events
   uvss.start()                ────────► POST /api/session/start
                                              ▲
                                              │
                                   ROS node / sensor can POST
                                   to the same endpoint
```

Your site stays exactly as it is. You add three things: an `<img>`, a
WebSocket listener, and two buttons. The edge service is a separate process —
it does not need to live on the same machine as your website.

---

## Step 1 — start the service

On the edge computer:

```bash
cd edge_deploy
install.bat          # Windows   (first time only)
./install.sh         # Linux     (first time only)

run.bat              # Windows
./run.sh             # Linux
```

Find the machine's LAN address:

```bash
ipconfig             # Windows — look for IPv4 Address
ip addr              # Linux
```

Everything below uses `EDGE_IP` — substitute your actual address, for example
`192.168.68.150`.

> If your website runs on the **same machine** as the service, use
> `http://localhost:8000` and skip most of the network concerns below.

---

## Step 2 — check it from your browser

Before writing any code, confirm the service is reachable **from the machine
running your browser**:

| Open this | You should see |
| --- | --- |
| `http://EDGE_IP:8000/api/status` | A JSON blob with `"camera_ok": true` |
| `http://EDGE_IP:8000/api/stream` | Live video |
| `http://EDGE_IP:8000/` | The reference dashboard |

If these do not load, fix that first — no amount of frontend code will help.
See [Gotchas](#gotchas-that-will-cost-you-an-hour).

---

## Step 3 — add the client to your site

Copy one file out of the package into your web assets:

```
edge_deploy/examples/uvss-client.js   →   your-site/js/uvss-client.js
```

Include it:

```html
<script src="/js/uvss-client.js"></script>
```

Or, if you use a bundler:

```js
import UvssClient from "./uvss-client.js";
```

It has no dependencies and handles WebSocket reconnection for you.

> You can skip this file entirely and call the REST/WebSocket endpoints
> directly — see [API.md](API.md). The client just saves you the boilerplate.

---

## Step 4 — the three integration points

### 4.1 Live video

```html
<img id="feed" alt="live feed">
```

```js
const uvss = new UvssClient("http://EDGE_IP:8000");
document.getElementById("feed").src = uvss.streamUrl();
```

That is the entire video integration. It is an MJPEG stream, which browsers
render natively — no video player, no WebRTC, no codec setup.

Add a reload handler so a service restart doesn't leave a dead image:

```js
const feed = document.getElementById("feed");
feed.onerror = () => {
  setTimeout(() => { feed.src = uvss.streamUrl() + "?t=" + Date.now(); }, 1500);
};
```

### 4.2 START / STOP

```html
<button id="start">START</button>
<button id="stop" disabled>STOP</button>
```

```js
document.getElementById("start").onclick = () => uvss.start("website");
document.getElementById("stop").onclick  = () => uvss.stop("website");
```

The string is just a label recorded with the session, so you can later tell
what triggered it (`"website"`, `"ros"`, `"radar"`).

### 4.3 Results

```js
uvss.on("status", (s) => {
  // fires once per second
  const running = !!s.session;
  document.getElementById("start").disabled = running;
  document.getElementById("stop").disabled = !running;
  document.getElementById("fps").textContent = s.fps + " FPS";
});

uvss.on("person", (p) => {
  // fires whenever a subject is found or their best images improve
  renderPerson(p);
});

uvss.on("stopped", (session) => {
  // session finished — clip is ready
  document.getElementById("clip").src = uvss.url(session.clip_url);
});

uvss.connect();   // don't forget this
```

Each person looks like:

```js
{
  identity: "1",
  class_name: "person",
  best_score: 0.724,
  images: [
    { crop: "/session-files/.../crop/q0.724_f45.jpg",
      full: "/session-files/.../full/q0.724_f45.jpg",
      score: 0.724 },
    // …up to 5, best first
  ]
}
```

Two images per shot: `crop` is the person cut out, `full` is the whole frame
with bounding boxes drawn. Paths are relative — `uvss.url()` makes them
absolute:

```js
function renderPerson(p) {
  const html = p.images.map(im => {
    const u = uvss.imageUrls(im);        // {crop, full, score} absolute
    return `<img src="${u.crop}" onclick="window.open('${u.full}')">`;
  }).join("");
  document.getElementById("people").insertAdjacentHTML("beforeend",
    `<div><b>#${p.identity}</b> ${p.class_name} ${html}</div>`);
}
```

---

## Framework snippets

### Plain HTML

A complete working page is at `edge_deploy/examples/integration-example.html`.
Open it in a browser, change `EDGE` at the top, and it works. Copy what you
need into your own page.

### React

```jsx
import { useEffect, useState } from "react";
import UvssClient from "./uvss-client";

const uvss = new UvssClient("http://EDGE_IP:8000");

export function LiveDetection() {
  const [status, setStatus] = useState(null);
  const [people, setPeople] = useState([]);
  const [clip, setClip] = useState(null);

  useEffect(() => {
    uvss.on("status", setStatus);
    uvss.on("person", () => setPeople(uvss.people()));
    uvss.on("started", () => { setPeople([]); setClip(null); });
    uvss.on("stopped", (s) => setClip(uvss.url(s.clip_url)));
    uvss.connect();
    return () => uvss.disconnect();       // clean up on unmount
  }, []);

  const running = !!status?.session;

  return (
    <div>
      <img src={uvss.streamUrl()} alt="live" />
      <button onClick={() => uvss.start("web")} disabled={running}>START</button>
      <button onClick={() => uvss.stop("web")} disabled={!running}>STOP</button>

      {people.map((p) => (
        <div key={p.identity}>
          <b>#{p.identity}</b> {p.class_name} — Q {p.best_score}
          {p.images.map((im, i) => (
            <img key={i} src={uvss.url(im.crop)} width={80} />
          ))}
        </div>
      ))}

      {clip && <video src={clip} controls />}
    </div>
  );
}
```

### Vue 3

```vue
<script setup>
import { ref, onMounted, onUnmounted } from "vue";
import UvssClient from "./uvss-client";

const uvss = new UvssClient("http://EDGE_IP:8000");
const status = ref(null);
const people = ref([]);

onMounted(() => {
  uvss.on("status", (s) => (status.value = s));
  uvss.on("person", () => (people.value = uvss.people()));
  uvss.connect();
});
onUnmounted(() => uvss.disconnect());
</script>

<template>
  <img :src="uvss.streamUrl()" />
  <button @click="uvss.start('web')" :disabled="!!status?.session">START</button>
  <button @click="uvss.stop('web')" :disabled="!status?.session">STOP</button>

  <div v-for="p in people" :key="p.identity">
    <b>#{{ p.identity }}</b>
    <img v-for="(im, i) in p.images" :key="i" :src="uvss.url(im.crop)" width="80" />
  </div>
</template>
```

### PHP / Django / Rails / any server-rendered site

Nothing changes. The integration is entirely client-side JavaScript — your
backend never talks to the edge service. Just include `uvss-client.js` in your
template and add the markup above.

---

## Triggering from ROS instead of a button

Your website does not have to be the trigger. Anything that can make an HTTP
POST can start and stop a session, and the website will see it happen live via
the WebSocket:

```bash
curl -X POST "http://EDGE_IP:8000/api/session/start?trigger=radar"
```

The bundled bridge converts a ROS topic or a hardware pin into those calls:

```bash
python ros_bridge.py --mode ros2 --topic /uvss/session_active \
                     --server http://EDGE_IP:8000
```

It expects `std_msgs/Bool` — `True` starts, `False` stops.

Your page needs no changes: the `session_started` / `session_stopped` events
arrive over the WebSocket regardless of who triggered them. This is worth
testing early — run `--mode test` (toggles every 15 s, no hardware needed) and
watch your UI react.

---

## Gotchas that will cost you an hour

### Your site is HTTPS, the edge service is HTTP

**This is the most common blocker.** Browsers refuse to load `http://` content
into an `https://` page ("mixed content"), and they will not tell you clearly —
the image just stays blank and the WebSocket silently fails.

Three ways out:

1. **Serve your site over HTTP too** while developing — simplest.
2. **Reverse-proxy the edge service** through the same domain as your site, so
   everything is same-origin HTTPS. With nginx:

   ```nginx
   location /uvss/ {
       proxy_pass http://EDGE_IP:8000/;
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;      # required for WebSocket
       proxy_set_header Connection "upgrade";
       proxy_buffering off;                         # required for MJPEG
   }
   ```

   Then use `new UvssClient(window.location.origin + "/uvss")`.

   The `proxy_buffering off` line matters — without it nginx buffers the MJPEG
   stream and the video never appears.

3. **Put a TLS certificate on the edge service** (more work; usually not worth
   it on a private network).

### CORS errors in the console

The service allows all origins by default, so this normally works out of the
box. If you locked it down, make sure your site's exact origin is listed:

```bash
run.bat --cors-origins http://your-site.com,http://localhost:3000
```

Include the scheme and port. `http://site.com` and `https://site.com` are
different origins.

### Nothing loads from another machine

The service binds `0.0.0.0` by default, so it listens on the network. Windows
Firewall usually blocks the port:

```powershell
netsh advfirewall firewall add rule name="UVSS Edge" dir=in action=allow protocol=TCP localport=8000
```

Test with `http://EDGE_IP:8000/api/status` in a browser on the other machine
before debugging code.

### The video works but events never arrive

You forgot `uvss.connect()`. The MJPEG feed is an independent `<img>` and works
without the WebSocket, so video-but-no-data almost always means this.

### Images 404

Image paths from the API are **relative** (`/session-files/...`). Prefix them
with the service origin using `uvss.url(path)` or `uvss.imageUrls(image)`.

### Only one browser tab shows video

Each open stream is a live HTTP connection. That is fine for a handful of
viewers; for many simultaneous ones, put a reverse proxy in front or reduce
the resolution with `--width 960 --height 540`.

---

## Checklist

Work down this list — each step depends on the one above it.

- [ ] `run.bat` / `./run.sh` starts without errors on the edge computer
- [ ] `http://EDGE_IP:8000/api/status` shows `"camera_ok": true`
- [ ] `"providers"` contains `Dml` or `CUDA` (otherwise it is on CPU and slow)
- [ ] The same URLs load **from the machine running your browser**
- [ ] `uvss-client.js` is copied into your site and included
- [ ] `<img>` shows live video
- [ ] `uvss.connect()` is called, and `status` events arrive
- [ ] START enables/disables the buttons correctly
- [ ] `person` events arrive when someone is in frame
- [ ] Images render (use `uvss.url()` on the paths)
- [ ] `stopped` gives you a playable `clip_url`
- [ ] A ROS/curl trigger updates the page without touching the UI

---

## Reference

* **[API.md](API.md)** — every endpoint and payload
* **[README.md](README.md)** — install and run options
* `examples/integration-example.html` — a working page to copy from
* `examples/uvss-client.js` — the client itself, ~200 readable lines
