#!/bin/sh
# Runs as root under tini: make the volume writable by the desktop user, then drop privileges.
set -e
mkdir -p /data/workspace /data/home /data/profiles
# simplification: top-level chown only (a deep chown of a large volume is slow); everything
# below, /workspace/shared included, is created by the computer user itself.
chown computer:computer /data /data/* 2>/dev/null || true
exec setpriv --reuid=computer --regid=computer --init-groups \
    env HOME=/data/home python -m app.main
