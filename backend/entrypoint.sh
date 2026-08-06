#!/usr/bin/env bash
# Sources ROS, then hands off to whatever command the container was given.
set -e

source /usr/local/bin/ros_setup.sh

# Safety net. The normal workflow creates and edits packages on the host, so
# src/ stays host-owned — colcon writes only to build/ and install/, which are
# outside the bind mount. But if you do run `ros2 pkg create` inside the
# container, root owns the result and the host editor hits EACCES; this hands it
# back on the next start. Defaults to 1000:1000, no compose config needed.
if [ -d "${ROS_WS}/src" ]; then
    chown -R "${HOST_UID:-1000}:${HOST_GID:-1000}" "${ROS_WS}/src" || true
fi

exec "$@"
