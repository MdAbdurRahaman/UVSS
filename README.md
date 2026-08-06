# UVSS — Under Vehicle Surveillance System

Dubotech UVSS web console. Two app areas behind a mock sign-in:

- **Edge console** (`/edge/*`) — single-site operator view: live stitched undercarriage scan, 3D stereo, ANPR plates, risk score, operator decision, scan queue, history, telemetry, alerts, and **Setup** (enable/disable cameras, sensors, AI and connectivity subsystems).
- **Central command** (`/central/*`) — multi-site supervisor view: fleet overview, sites, watchlist, alerts, reports, analyst review queue, advanced search. Clicking a site opens a **live monitor inside Central** (`/central/site/:id`) — read-only mirror of that edge (live composite, cameras, plate, risk); it does NOT switch to the Edge dashboard.

Angular 17 (NgModule + SSR via Express), Tailwind, Docker — mirroring the
`dubotech_tracker` frontend conventions. The screens are ported from the
Claude Design project (navy `#0D2B52`, Nunito + JetBrains Mono).

## Sign in (mock — no backend yet)

Two **independently-authenticated** dashboards. The root `/` is a chooser; each
dashboard has its own login and its own session — signing into one does not
grant the other (sign in again to switch). Shared demo credentials:

| Field | Value |
|-------|-------|
| Username | `dubotech` |
| Password | `dubotech` |
| 2FA code | `123456` |

- `/` — landing chooser (Edge console / Central command)
- `/edge/login` → gates `/edge/*`
- `/central/login` → gates `/central/*`

Auth is a client-side mock (`AuthService`, scope `'edge' | 'central'`); each
session is a separate `localStorage` flag (`uvss-auth-edge`, `uvss-auth-central`).
The route guard reads `data.dashboard` and redirects to that dashboard's login.

## Run with Docker

```bash
docker compose up --build
# frontend → http://localhost:4017   (host 4017 → container SSR on 4000)
# backend  → ROS 2 container, no HTTP listener yet (8000 reserved)
```

## Run locally (dev)

```bash
cd frontend
npm install --legacy-peer-deps
npm start          # ng serve → http://localhost:4200
```

Production SSR build + serve:

```bash
cd frontend
npm run build:ssr
npm run serve:ssr  # node dist/frontend/server/main.js → http://localhost:4000
```

## Backend (ROS 2 Humble)

`backend/` is a colcon workspace that lives at `/ros2_ws` inside the container.
`backend/src/` is bind-mounted in, so it is the same directory on both sides:
**author packages on the host, build and run them in the container.** There are
no nodes yet — the container starts, sources ROS, and idles.

```bash
docker compose up -d --build backend
docker compose exec backend bash        # ROS is already sourced in this shell
ros2 topic list
```

### Creating a package

**Create and edit on the host, build in the container.** The host has ROS 2
Jazzy installed, and `ros2 pkg create` only writes a template — the generated
`package.xml` is format 3 and builds fine under the container's Humble. Doing it
host-side keeps every file owned by you, so your editor never hits EACCES.

```bash
cd backend/src
ros2 pkg create --build-type ament_python --license Apache-2.0 uvss_demo \
    --dependencies rclpy std_msgs
```

Write the node on the host at `backend/src/uvss_demo/uvss_demo/talker.py`, then
register it as an entry point in that package's `setup.py`:

```python
entry_points={
    'console_scripts': [
        'talker = uvss_demo.talker:main',
        'listener = uvss_demo.listener:main',
    ],
},
```

Build and run **in the container** — colcon writes to `/ros2_ws/build` and
`/ros2_ws/install`, both outside the bind mount, so `src/` stays yours:

```bash
docker compose exec backend bash
cd /ros2_ws
colcon build --symlink-install --packages-select uvss_demo
source install/setup.bash              # only needed in an already-open shell
ros2 run uvss_demo talker
```

`--symlink-install` means Python changes take effect without rebuilding; adding
or renaming an entry point still needs another `colcon build`. A fresh
`docker compose exec backend bash` picks up the overlay automatically.

Rebuild the image (`docker compose build backend`) when you change
`requirements.txt` or add a package with new apt-level dependencies — the image
build runs `rosdep install` over `src/` whenever a `package.xml` is present.

### Notes

- The container runs as root, so anything it writes into the bind-mounted `src/`
  comes out root-owned and your editor hits `EACCES: permission denied`. Sticking
  to host-side `ros2 pkg create` and host-side editing avoids this entirely. If
  it happens anyway, `entrypoint.sh` chowns `src/` back to `1000:1000` on the
  next `docker compose restart backend`, or fix it immediately with:

  ```bash
  docker compose exec -T backend chown -R 1000:1000 /ros2_ws/src
  ```
- DDS is pinned to `ROS_LOCALHOST_ONLY=1` on `ROS_DOMAIN_ID=42` with Fast DDS.
  Everything ROS runs in this one container, so no multicast has to cross the
  compose bridge network. Splitting nodes into a second container later means
  choosing between `network_mode: host` and a Fast DDS discovery server.
- Nothing listens on a port yet. When the FastAPI bridge lands, publish it as
  `8017:8000` — host 8000 is already taken by `dubodrop_backend`.

## Layout

```
frontend/
  src/app/
    core/{guards,services}   auth.guard (scope-aware), auth.service (mock, per-dashboard)
    landing/                 root dashboard chooser
    shared/sign-in           reusable login (credentials → OTP), scoped via route data
    modules/
      edge/                  edge-shell + login + console, scan, history, telemetry, alerts, setup (subsystem toggles)
      central/               central-shell + login + command, sites, site/:id (live edge monitor), watchlist, alerts, reports, review, search
  server.ts                  Express SSR entry (renderModule)
  Dockerfile                 node:20 multi-stage → SSR server on :4000
backend/
  Dockerfile                 ros:humble → colcon workspace at /ros2_ws
  entrypoint.sh              sources the ROS underlay + workspace overlay
  requirements.txt           pip deps (FastAPI bridge deps included, unused so far)
  src/                       ROS 2 packages go here (empty; bind-mounted into the container)
docker-compose.yml           frontend 4017:4000, backend (ROS 2)
```

## Assets

Vehicle/scan imagery lives in `frontend/src/assets/`. The two large
undercarriage "hero" composites (`undercarriage.jpg`, `undercarriage-3d.jpg`)
are generated placeholders — the originals exceeded the design-export size cap
and could not be pulled whole. Drop the real JPGs in over them to restore full
fidelity; every other asset is the real export.
