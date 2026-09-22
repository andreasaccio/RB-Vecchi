#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Eseguire con sudo: sudo ./update.sh" >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR=/opt/rb-vecchi

systemctl stop rb-vecchi.service
cp -a "$SCRIPT_DIR/rbvecchi" "$INSTALL_DIR/"
cp -a "$SCRIPT_DIR/wsgi.py" "$SCRIPT_DIR/run.py" "$SCRIPT_DIR/configure.py" "$SCRIPT_DIR/diagnose.py" "$SCRIPT_DIR/requirements.txt" "$SCRIPT_DIR/start.sh" "$INSTALL_DIR/"
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
install -m 0644 "$SCRIPT_DIR/rb-vecchi.service" /etc/systemd/system/rb-vecchi.service
systemctl daemon-reload
systemctl start rb-vecchi.service
systemctl --no-pager --full status rb-vecchi.service
