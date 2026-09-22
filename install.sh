#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Eseguire con sudo: sudo ./install.sh" >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR=/opt/rb-vecchi
SERVICE_USER=rbvecchi
ENV_FILE=/etc/rb-vecchi.env

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip ca-certificates

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0755 "$INSTALL_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 /var/lib/rb-vecchi

cp -a "$SCRIPT_DIR/rbvecchi" "$INSTALL_DIR/"
cp -a "$SCRIPT_DIR/wsgi.py" "$SCRIPT_DIR/run.py" "$SCRIPT_DIR/configure.py" "$SCRIPT_DIR/diagnose.py" "$SCRIPT_DIR/requirements.txt" "$SCRIPT_DIR/start.sh" "$INSTALL_DIR/"
chmod 0755 "$INSTALL_DIR/start.sh" "$INSTALL_DIR/configure.py" "$INSTALL_DIR/diagnose.py"

python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip wheel
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

"$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/configure.py" --output "$ENV_FILE"
chown root:"$SERVICE_USER" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

install -m 0644 "$SCRIPT_DIR/rb-vecchi.service" /etc/systemd/system/rb-vecchi.service
systemctl daemon-reload
systemctl enable --now rb-vecchi.service

HOSTNAME_SHORT=$(hostname -s 2>/dev/null || echo rb-vecchi)
IP_ADDRESS=$(hostname -I 2>/dev/null | awk '{print $1}')
PORT=$(sed -n 's/^LISTEN_PORT=//p' "$ENV_FILE" | tr -d '"' | tail -n 1)
PORT=${PORT:-8080}

echo
echo "Installazione completata."
echo "Stato servizio: systemctl status rb-vecchi"
echo "Log: journalctl -u rb-vecchi -f"
echo "Pagina: http://${HOSTNAME_SHORT}.local:${PORT}"
if [ -n "$IP_ADDRESS" ]; then
  echo "Oppure: http://${IP_ADDRESS}:${PORT}"
fi
