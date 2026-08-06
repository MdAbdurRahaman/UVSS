FROM ros:humble

# The ROS setup scripts are bash-only and use `source`, which /bin/sh (dash)
# does not provide. Every RUN below therefore needs bash, not sh.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive \
    ROS_DISTRO=humble \
    ROS_WS=/ros2_ws \
    PYTHONUNBUFFERED=1

# ---------------------------------------------------------
# 1) Base tools, ROS build tooling, camera/serial deps
# ---------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip \
        python3-setuptools \
        python3-colcon-common-extensions \
        python3-rosdep \
        python3-vcstool \
        python3-yaml \
        python3-gi \
        git \
        build-essential \
        pkg-config \
        curl \
        nano \
        locales \
        ca-certificates \
        bash-completion \
        libglib2.0-dev \
        # GStreamer — for a future camera_node (RTSP / v4l capture)
        gstreamer1.0-tools \
        gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-plugins-ugly \
        gstreamer1.0-libav \
        gstreamer1.0-rtsp \
        libgstreamer1.0-dev \
        libgstreamer-plugins-base1.0-dev \
        # camera / serial / network diagnostics
        v4l-utils \
        usbutils \
        net-tools \
        iproute2 \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------
# 2) Locale
# ---------------------------------------------------------
RUN locale-gen en_US.UTF-8 && \
    update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

ENV LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8

# ---------------------------------------------------------
# 3) rosdep (the base image already ran `rosdep init`)
# ---------------------------------------------------------
RUN rosdep init 2>/dev/null || true; rosdep update --rosdistro "$ROS_DISTRO"

# ---------------------------------------------------------
# 4) Python dependencies
# ---------------------------------------------------------
WORKDIR ${ROS_WS}

COPY requirements.txt ./
RUN pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt

# ---------------------------------------------------------
# 5) Shell setup
#
# `docker exec` skips the ENTRYPOINT, so exec'd shells need their own hook into
# ros_setup.sh: /etc/bash.bashrc covers interactive ones, $BASH_ENV (set further
# down) covers `bash -c`. /root/.bashrc alone would miss the latter.
# ---------------------------------------------------------
COPY ros_setup.sh entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/ros_setup.sh /usr/local/bin/entrypoint.sh && \
    echo 'source /usr/local/bin/ros_setup.sh' >> /etc/bash.bashrc

# ---------------------------------------------------------
# 6) Build the workspace
#
# src/ may hold no packages yet — rosdep is skipped until a package.xml exists,
# and colcon emits install/setup.bash regardless, so the entrypoint always has
# an overlay to source. No `|| true` on rosdep: a missing dependency should fail
# the build, not surface later as a broken node.
# ---------------------------------------------------------
COPY src/ ./src/

RUN source "/opt/ros/${ROS_DISTRO}/setup.bash" && \
    if find src -name package.xml -print -quit | grep -q .; then \
        apt-get update && \
        rosdep install --from-paths src --ignore-src -r -y && \
        rm -rf /var/lib/apt/lists/*; \
    else \
        echo "src/ holds no ROS packages yet — skipping rosdep"; \
    fi && \
    colcon build --symlink-install

# ---------------------------------------------------------
# 7) DDS: single container, loopback only — no multicast needed across the
#     compose bridge network.
# ---------------------------------------------------------
ENV ROS_LOCALHOST_ONLY=1 \
    ROS_DOMAIN_ID=42 \
    RMW_IMPLEMENTATION=rmw_fastrtps_cpp

# Set after the colcon build so it cannot leak into the build's own subshells.
ENV BASH_ENV=/usr/local/bin/ros_setup.sh

# Reserved for the FastAPI bridge (not implemented yet).
EXPOSE 8000

WORKDIR ${ROS_WS}/src

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash", "-c", "echo \"UVSS backend up — ROS 2 ${ROS_DISTRO}. No nodes yet; run: docker compose exec backend bash\"; sleep infinity"]
