#!/bin/sh
set -e

USER="${SECURITY_USER:-admin}"
PASS="${SECURITY_PASSWORD:-buildwise2026}"

echo "[BuildWise Security Gateway] Initializing htpasswd for user: $USER"
htpasswd -bc /etc/nginx/.htpasswd "$USER" "$PASS"

exec nginx -g 'daemon off;'
