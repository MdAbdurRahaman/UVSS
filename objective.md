# UVSS — System Objective & Architecture Roadmap

## 🎯 Primary Objective

The goal of this project is to build an integrated **Under Vehicle Surveillance System (UVSS)** powered by **ROS 2** and Edge AI inference, displaying real-time telemetry, camera streams, sensor feeds, and AI threat detection within the Angular web dashboard.

---

## 🏗️ System Architecture & Data Flow

```
┌───────────────────────────────────────────────────────────┐
│                      Hardware Layer                       │
│    Undercarriage Cameras / Side Cameras / ANPR Cameras    │
│            Inductive Loop Sensors & Speed Radar           │
└─────────────────────────────┬─────────────────────────────┘
                              │ Real-time Streams & Data
                              ▼
┌───────────────────────────────────────────────────────────┐
│                    ROS 2 Middleware                       │
│   • Camera Feed Nodes (Image/RTSP Publishers)              │
│   • Sensor Trigger Nodes (Loop & Speed Telemetry)         │
│   • Decision & State Control Topics                       │
└─────────────────────────────┬─────────────────────────────┘
                              │ ROS 2 Topics
                              ▼
┌───────────────────────────────────────────────────────────┐
│              Edge AI Model Layer (`edge_deploy`)          │
│   • Model Location: `edge_deploy/`                        │
│   • Models: Foreign Object Threat Detection, ANPR OCR,    │
│     Driver Face Recognition, Anomaly Baseline Comparison  │
└─────────────────────────────┬─────────────────────────────┘
                              │ Inference Results & Metadata
                              ▼
┌───────────────────────────────────────────────────────────┐
│                  Web Dashboard (Angular)                  │
│   • Live Stitched Undercarriage & 3D Stereo View          │
│   • Top Priority Operator Decision (Pass / Halt)          │
│   • Vehicle Cameras Feed                                  │
│   • Number Plate (ANPR) Module                            │
│   • Driver Face Capture & Recognition Module              │
│   • Risk Score & Threat Breakdown                         │
└───────────────────────────────────────────────────────────┘
```

---

## 📋 Key Execution Phases

1. **Phase 1: Frontend Layout & Component Modularization** *(Current)*
   - Reposition **Operator Decision** to top priority in the control sidebar.
   - Implement standalone **Driver Face Capture Module** (`DriverFaceComponent`).
   - Refine design aesthetics and responsive layouts.

2. **Phase 2: Edge AI Integration (`edge_deploy`)**
   - Store prebuilt AI models under `edge_deploy/`.
   - Setup inference worker nodes reading ROS 2 image topics and producing bounding boxes, confidence scores, and plate/face metadata.

3. **Phase 3: ROS 2 Pipeline & FastAPI Bridge Integration**
   - Establish FastAPI WebSocket / WebRTC bridge to relay ROS 2 topics to the Angular UI.
   - Integrate live camera feeds (ANPR Front/Rear, Side Left/Right, Undercarriage, Driver Face Camera).

4. **Phase 4: Multi-Site Central Command & Reporting**
   - Connect Edge consoles to Central Command dashboard for site monitoring and analyst review queue.
