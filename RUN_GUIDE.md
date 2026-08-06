# Dubotech UVSS — Run Guide & Setup Documentation

This guide provides step-by-step instructions for running, configuring, and deploying the **Dubotech Under Vehicle Surveillance System (UVSS)**.

---

## 🚀 Quick Start (Local Development)

### 1. Prerequisites

- **Node.js**: v18.13.0 or higher (v20.x LTS recommended)
- **npm**: v9.x or higher
- **(Optional) Docker & Docker Compose**: For containerized deployment & ROS 2 backend

### 2. Setting Up Environment & Installing Dependencies

If Node.js is not already installed on your system, you can use **NVM** (Node Version Manager):

```bash
# Load NVM (if already installed) or install Node 20 LTS:
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# Install & set Node.js v20
nvm install 20
nvm alias default 20
nvm use 20
```

Navigate to the `frontend/` directory and install project dependencies:

```bash
cd frontend
npm install --legacy-peer-deps
```

### 3. Running the Frontend Development Server

Start the Angular dev server:

```bash
cd frontend
npm start
```

- **Access URL**: [http://localhost:4200](http://localhost:4200)
- **Live Reloading**: Enabled by default on code changes.

---

## 🏭 Production Build & SSR Execution

To build and serve the application using Server-Side Rendering (SSR) with Express:

```bash
cd frontend

# 1. Build client and server bundles
npm run build:ssr

# 2. Run Express SSR server
npm run serve:ssr
```

- **Access URL**: [http://localhost:4000](http://localhost:4000)

---

## 🐳 Docker Deployment

To run the full stack (Frontend SSR container + ROS 2 Backend environment) using Docker Compose:

```bash
# Build and start all services in detached mode
docker compose up --build -d

# Check service status
docker compose ps

# View container logs
docker compose logs -f frontend
```

- **Frontend Container URL**: [http://localhost:4017](http://localhost:4017) (Host 4017 maps to container port 4000)
- **Backend ROS 2 Container**: Runs ROS 2 Humble workspace environment

---

## 🔑 Demo Access Credentials

The application features two independently-authenticated consoles behind a mock sign-in system:

| Field | Value |
|-------|-------|
| **Username** | `dubotech` |
| **Password** | `dubotech` |
| **2FA Code** | `123456` |

### Application Routes:

- `/` — **Landing Chooser**: Choose between Edge Console & Central Command
- `/edge/login` → **Edge Console**: Live stitched undercarriage scan, 3D stereo view, ANPR plate recognition, risk scoring, camera/sensor setup.
- `/central/login` → **Central Command**: Multi-site fleet overview, site monitoring, watchlists, risk analytics, and search.

---

## 🤖 Backend Setup (ROS 2 Humble / Jazzy)

The `backend/` workspace contains ROS 2 workspace configurations (`colcon`).

### Running ROS 2 in Docker:

```bash
# Start backend container
docker compose up -d --build backend

# Open interactive ROS shell inside container
docker compose exec backend bash

# Build colcon workspace inside container
cd /ros2_ws
colcon build --symlink-install
source install/setup.bash
```

---

## 🛠 Summary of Service Ports

| Service | Mode | URL / Port |
|---------|------|------------|
| **Angular Dev Server** | Local Dev | `http://localhost:4200` |
| **Express SSR Server** | Production Local | `http://localhost:4000` |
| **Docker Frontend** | Containerized | `http://localhost:4017` |
| **ROS 2 Backend** | Containerized | Port `8017` (reserved for FastAPI bridge) |
