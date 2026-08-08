#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
web/ros_bridge.py
=================
Translate a ROS topic (or a plain GPIO / serial / TCP sensor) into START and
STOP calls on the edge service.

The edge service deliberately knows nothing about ROS — it only exposes

    POST /api/session/start?trigger=<name>
    POST /api/session/stop?trigger=<name>

so ANY trigger source can drive it. This file is one such source; it is not
required for the service to run.

Supported modes
---------------
  ros2   : rclpy, subscribes to a std_msgs/Bool (True = start, False = stop)
  ros1   : rospy, same contract
  gpio   : Raspberry Pi GPIO pin, rising edge = start, falling = stop
  serial : reads lines from a serial port; "START"/"STOP" (case-insensitive)
  test   : prints what it would do, then alternates start/stop on a timer

Usage
-----
    python web/ros_bridge.py --mode ros2 --topic /uvss/session_active
    python web/ros_bridge.py --mode ros1 --topic /uvss/session_active
    python web/ros_bridge.py --mode gpio --pin 17
    python web/ros_bridge.py --mode serial --port COM3 --baud 115200
    python web/ros_bridge.py --mode test

    # point at a remote edge box
    python web/ros_bridge.py --mode ros2 --server http://192.168.1.50:8000
"""

from __future__ import annotations

import argparse
import sys
import time


def log(msg: str) -> None:
    print(f"[ros_bridge] {msg}", flush=True)


class EdgeClient:
    """Thin HTTP client. Debounces so a chattering sensor cannot spam the API."""

    def __init__(self, server: str, trigger: str, min_interval: float = 0.5):
        self.server = server.rstrip("/")
        self.trigger = trigger
        self.min_interval = float(min_interval)
        self._last_state: bool | None = None
        self._last_time = 0.0
        try:
            import requests
            self._requests = requests
        except ImportError:
            log("ERROR: the `requests` package is required -> pip install requests")
            sys.exit(1)

    def set_active(self, active: bool) -> None:
        now = time.time()
        if active == self._last_state:
            return                                  # no change
        if now - self._last_time < self.min_interval:
            return                                  # debounce
        self._last_state = active
        self._last_time = now

        path = "/api/session/start" if active else "/api/session/stop"
        url = f"{self.server}{path}"
        try:
            r = self._requests.post(url, params={"trigger": self.trigger},
                                    timeout=5)
            data = r.json() if r.content else {}
            if data.get("ok"):
                sess = data.get("session", {})
                log(f"{'START' if active else 'STOP'} ok "
                    f"(session {sess.get('id', '?')})")
            else:
                log(f"{'START' if active else 'STOP'} refused: "
                    f"{data.get('reason', r.status_code)}")
        except Exception as exc:  # noqa: BLE001 — a sensor must not crash on a dropped link
            log(f"request failed: {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
def run_ros2(client: EdgeClient, topic: str) -> None:
    try:
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import Bool
    except ImportError:
        log("ERROR: rclpy / std_msgs not found. Source your ROS 2 setup first:")
        log("    call C:\\dev\\ros2\\local_setup.bat     (Windows)")
        log("    source /opt/ros/humble/setup.bash       (Linux)")
        sys.exit(1)

    class Bridge(Node):
        def __init__(self) -> None:
            super().__init__("uvss_edge_bridge")
            self.create_subscription(Bool, topic, self._cb, 10)
            log(f"ROS 2: subscribed to {topic} (std_msgs/Bool)")

        def _cb(self, msg) -> None:
            client.set_active(bool(msg.data))

    rclpy.init()
    node = Bridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


def run_ros1(client: EdgeClient, topic: str) -> None:
    try:
        import rospy
        from std_msgs.msg import Bool
    except ImportError:
        log("ERROR: rospy / std_msgs not found. Source your ROS 1 setup first:")
        log("    source /opt/ros/noetic/setup.bash")
        sys.exit(1)

    rospy.init_node("uvss_edge_bridge", anonymous=True)
    rospy.Subscriber(topic, Bool, lambda m: client.set_active(bool(m.data)))
    log(f"ROS 1: subscribed to {topic} (std_msgs/Bool)")
    rospy.spin()


def run_gpio(client: EdgeClient, pin: int, poll: float = 0.05) -> None:
    try:
        import RPi.GPIO as GPIO
    except ImportError:
        log("ERROR: RPi.GPIO not found (Raspberry Pi only)")
        sys.exit(1)

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    log(f"GPIO: watching BCM pin {pin} (HIGH = session active)")
    try:
        while True:
            client.set_active(bool(GPIO.input(pin)))
            time.sleep(poll)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()


def run_serial(client: EdgeClient, port: str, baud: int) -> None:
    try:
        import serial
    except ImportError:
        log("ERROR: pyserial not found -> pip install pyserial")
        sys.exit(1)

    log(f"serial: reading {port} @ {baud} — expecting START / STOP lines")
    with serial.Serial(port, baud, timeout=1) as ser:
        while True:
            try:
                line = ser.readline().decode("utf-8", "ignore").strip().upper()
            except Exception as exc:  # noqa: BLE001
                log(f"serial read error: {exc}")
                time.sleep(0.5)
                continue
            if not line:
                continue
            if "START" in line:
                client.set_active(True)
            elif "STOP" in line:
                client.set_active(False)


def run_test(client: EdgeClient, period: float) -> None:
    log(f"test mode: toggling every {period}s (Ctrl-C to stop)")
    state = False
    try:
        while True:
            state = not state
            client.set_active(state)
            time.sleep(period)
    except KeyboardInterrupt:
        log("stopping; sending a final STOP")
        client.set_active(False)


# --------------------------------------------------------------------------- #
def main() -> int:
    p = argparse.ArgumentParser(
        description="Bridge a ROS topic / sensor to the UVSS edge service.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--mode", default="test",
                   choices=["ros2", "ros1", "gpio", "serial", "test"])
    p.add_argument("--server", default="http://localhost:8000",
                   help="edge service base URL")
    p.add_argument("--topic", default="/uvss/session_active")
    p.add_argument("--pin", type=int, default=17, help="GPIO BCM pin")
    p.add_argument("--port", default="COM3", help="serial port")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--period", type=float, default=15.0,
                   help="test mode toggle period, seconds")
    p.add_argument("--trigger", default=None,
                   help="label recorded against the session (default: mode)")
    p.add_argument("--debounce", type=float, default=0.5)
    args = p.parse_args()

    client = EdgeClient(args.server, args.trigger or args.mode, args.debounce)
    log(f"edge service: {args.server}")

    if args.mode == "ros2":
        run_ros2(client, args.topic)
    elif args.mode == "ros1":
        run_ros1(client, args.topic)
    elif args.mode == "gpio":
        run_gpio(client, args.pin)
    elif args.mode == "serial":
        run_serial(client, args.port, args.baud)
    else:
        run_test(client, args.period)
    return 0


if __name__ == "__main__":
    sys.exit(main())
