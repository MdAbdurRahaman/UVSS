#!/usr/bin/env bash
# Sources the ROS underlay plus the workspace overlay.
#
# Pulled in from three places so every shell in the container has ROS on PATH:
#   - entrypoint.sh                        (the container's main process)
#   - /etc/bash.bashrc                     (interactive `docker compose exec backend bash`)
#   - $BASH_ENV                            (non-interactive `... exec -T backend bash -c ...`)
# `docker exec` skips the image ENTRYPOINT, so the entrypoint alone is not enough.
#
# No `set -u` anywhere near this: the ROS setup scripts read unset variables on
# purpose and abort with "AMENT_TRACE_SETUP_FILES: unbound variable".

[ -n "${UVSS_ROS_SOURCED:-}" ] && return 0
export UVSS_ROS_SOURCED=1

source "/opt/ros/${ROS_DISTRO}/setup.bash"

if [ -f "${ROS_WS}/install/setup.bash" ]; then
    source "${ROS_WS}/install/setup.bash"
fi
