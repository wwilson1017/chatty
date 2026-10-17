#!/bin/sh
# Runs as root under tini: make the volume writable by the desktop user, then drop privileges.
set -e
mkdir -p /data/workspace /data/workspace/shared /data/home /data/profiles
# simplification: top-level chown only (a deep chown of a large volume is slow); everything
# below is created by the computer user anyway.
chown computer:computer /data /data/* 2>/dev/null || true
exec setpriv --reuid=computer --regid=computer --init-groups \
    env HOME=/data/home python -m app.main
