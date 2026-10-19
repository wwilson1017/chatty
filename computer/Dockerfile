# Chatty virtual computer: a Linux desktop (Chromium, terminal, files) with a control API.
# Built for linux/amd64 and linux/arm64; everything here is in Debian's repos or multi-arch.
FROM python:3.12-slim-trixie

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Desktop stack + the apps the card promises (terminal, file manager, LibreOffice Writer/Calc).
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium xvfb openbox x11vnc xdotool x11-utils tini sudo \
      ca-certificates curl xz-utils procps \
      fonts-liberation fonts-dejavu-core fonts-noto-color-emoji fonts-noto-cjk \
      xterm pcmanfm libreoffice-writer libreoffice-calc \
    && rm -rf /var/lib/apt/lists/*

# Node 22 (npx for command MCP servers) and uv (uvx) for the same.
ARG NODE_VERSION=22.23.3
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in amd64) node_arch=x64 ;; arm64) node_arch=arm64 ;; *) echo "unsupported arch $arch" && exit 1 ;; esac \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" \
       | tar -xJ -C /usr/local --strip-components=1 --exclude='*/CHANGELOG.md' --exclude='*/README.md' --exclude='*/LICENSE'
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /usr/local/bin/

RUN useradd -m -s /bin/bash -u 1000 computer \
    && echo "computer ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/computer \
    && chmod 0440 /etc/sudoers.d/computer \
    && mkdir -p /data && ln -s /data/workspace /workspace

COPY requirements.txt /opt/computer/requirements.txt
RUN pip install -r /opt/computer/requirements.txt

COPY openbox/rc.xml /etc/xdg/openbox/rc.xml
COPY app /opt/computer/app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV HOME=/data/home \
    DISPLAY=:1 \
    PORT=8080 \
    PYTHONPATH=/opt/computer
WORKDIR /opt/computer
EXPOSE 8080
ENTRYPOINT ["tini", "--", "/entrypoint.sh"]
