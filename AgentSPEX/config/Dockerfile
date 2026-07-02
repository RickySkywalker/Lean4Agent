# Dockerfile — Virtual Sandbox Desktop with MCP + Control API
FROM mambaorg/micromamba:1.5.8

USER root
SHELL ["/bin/bash", "-lc"]

# Put conda python first
ENV PATH=/opt/conda/bin:${PATH}
ENV MAMBA_NO_BANNER=1
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
ENV PIP_NO_CACHE_DIR=1

# System deps for X, VNC, Chromium
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    xvfb fluxbox xterm tmux xauth x11-apps \
    x11vnc novnc websockify x11-utils x11-xserver-utils \
    libglib2.0-0 libnss3 libnspr4 libdrm2 libgbm1 libxkbcommon0 libxcomposite1 \
    libxrandr2 libxdamage1 libxfixes3 libxi6 libxrender1 libxshmfence1 \
    libxext6 libx11-xcb1 libxcb1 libxcb-dri3-0 \
    libgtk-3-0 libatk-bridge2.0-0 libatspi2.0-0 libpango-1.0-0 libpangocairo-1.0-0 \
    libcups2 libasound2 fonts-dejavu fontconfig ca-certificates curl tini \
    sudo vim openssh-server git \
    at-spi2-core python3-gi python3-pyatspi python3-dbus dbus-x11 gir1.2-atspi-2.0 \
    tesseract-ocr tesseract-ocr-eng wmctrl xdotool \
    gnome-screenshot scrot imagemagick \
    ripgrep sed tree \
    build-essential gcc g++ make \
    # Build tools for compiling Python C extensions (torch-scatter, etc.)
 && rm -rf /var/lib/apt/lists/*

# Create agent user with sudo privileges
# UID pinned to 1000 to match the typical host user, so the bind-mounted /workspace is writable
# (base image ships mambauser=57439, so an unpinned useradd would get 57440 and no write access)
# Created before the python toolchain so /opt/conda can be agent-owned from the start:
# a standalone `chown -R` in a later RUN forces overlayfs to copy up the whole
# multi-GB tree into a new layer (slow, and doubles the image size)
RUN useradd -ms /bin/bash -u 1000 agent && \
    echo 'agent:passw0rd' | chpasswd && \
    echo 'agent ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/agent && \
    mkdir -p /home/agent/.ssh && \
    chmod 700 /home/agent/.ssh && \
    chown -R agent:agent /home/agent/.ssh && \
    # the bash -l SHELL sources /etc/profile, which resets PATH and drops the
    # ENV conda prefix; restore it for agent login shells (RUN steps, ssh)
    echo 'export PATH=/opt/conda/bin:$PATH' >> /home/agent/.profile

# Python toolchain via micromamba; chown in the same layer that creates the
# tree (cheap metadata update, no copy-up)
ARG PYTHON_VERSION=3.12
RUN micromamba install -y -p /opt/conda -c conda-forge python=${PYTHON_VERSION} pip \
 && micromamba clean --all -y \
 && chown -R agent:agent /opt/conda

# Shared workspace, tool and browser dirs — agent-owned from the start
RUN mkdir -p /workspace /opt/tools /opt/playwright-browsers /opt/conda/envs \
 && chown agent:agent /workspace /opt/tools /opt/playwright-browsers /opt/conda/envs

# Python deps (pip into /opt/conda), as agent so site-packages stays agent-owned.
# fastmcp and playwright must stay pinned to the same versions as
# src/sandbox_vm/requirements.txt: an unpinned install here gets silently
# up/downgraded by the later requirements install, leaving a mixed fastmcp tree
# or a playwright whose matching chromium build was never downloaded
USER agent
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir fastapi uvicorn httpx fastmcp==2.12.2 pydantic playwright==1.54.0 websockets beautifulsoup4 PyPDF2

# Install Playwright system dependencies (needs root: runs apt under the hood)
USER root
RUN playwright install-deps chromium

# Pre-download Playwright Chromium (as agent, into the agent-owned browsers dir)
USER agent
RUN python -m playwright install chromium

# Make sure chromium is in PATH
USER root
RUN CHROMIUM_PATH=$(python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()") && \
    echo "Chromium installed at: $CHROMIUM_PATH" && \
    ln -s "$CHROMIUM_PATH" /usr/local/bin/chromium && \
    ls -l /usr/local/bin/chromium

# sshd: agent logins only, no root
RUN mkdir /var/run/sshd && \
    usermod -s /usr/sbin/nologin root && \
    sed -i 's/^PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config && \
    echo 'AllowUsers agent' >> /etc/ssh/sshd_config

# Install vm package
ARG VM_PACKAGE=sandbox_vm
ENV VM_PACKAGE=${VM_PACKAGE}
RUN mkdir -p /home/agent/app/src && chown agent:agent /home/agent/app /home/agent/app/src
WORKDIR /home/agent/app/src

COPY --chown=agent:agent ./src .
USER agent
RUN pip install -r ${VM_PACKAGE}/requirements.txt

ENV HOME=/home/agent
ENV PATH=/opt/conda/bin:${PATH}

# Entrypoint
ENTRYPOINT ["/usr/bin/tini", "-s", "--"]
CMD ["sh", "-c", "bash /home/agent/app/src/${VM_PACKAGE}/start.sh"]
