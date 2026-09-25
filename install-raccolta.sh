#!/bin/sh
# Installa o aggiorna i raccoglitori dati (rb-carica, rb-plc, rb-link).
# Idempotente. NON tocca il servizio del basculante (rb-vecchi.service).
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Eseguire con sudo: sudo ./install-raccolta.sh" >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SRC="$SCRIPT_DIR/raccolta"
INSTALL_DIR=/opt/rb-raccolta
DATA_DIR=/var/lib/rb-raccolta
SERVICE_USER=rbraccolta
PROGRAMMI="giornaliero.py rb-carica.py rb-plc.py rb-link.py"
UNITA="rb-carica.service rb-plc.service rb-link.service"

# Un'unità transitoria con lo stesso nome avrebbe la precedenza sul file in /etc.
for u in $UNITA; do
  if [ "$(systemctl show -p Transient --value "$u" 2>/dev/null)" = yes ]; then
    echo "$u è ancora un'unità transitoria: fermarla prima (systemctl stop $u)." >&2
    exit 1
  fi
done

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --no-create-home \
    --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0755 "$INSTALL_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0755 "$DATA_DIR"
# I file migrati da migra-dati.py (lanciato da root) passano all'utente.
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"

for f in $PROGRAMMI; do
  install -m 0644 "$SRC/$f" "$INSTALL_DIR/$f"
done
chmod 0755 "$INSTALL_DIR"/rb-*.py
for u in $UNITA; do
  install -m 0644 "$SRC/$u" "/etc/systemd/system/$u"
done

systemctl daemon-reload
systemctl enable $UNITA
systemctl restart $UNITA

echo
ESITO=0
# Il ping deve riuscire all'utente, e anche con NoNewPrivileges come nell'unità:
# lì le capability del file /usr/bin/ping non valgono e serve il socket ICMP
# non privilegiato (net.ipv4.ping_group_range).
if sudo -u "$SERVICE_USER" ping -c1 -W1 192.168.1.1 >/dev/null 2>&1; then
  echo "ping come $SERVICE_USER: ok"
else
  echo "ATTENZIONE: $SERVICE_USER non riesce a fare ping a 192.168.1.1" >&2
  ESITO=2
fi
if systemd-run --quiet --wait --pipe --collect \
     -p User="$SERVICE_USER" -p NoNewPrivileges=true \
     -p RestrictAddressFamilies="AF_UNIX AF_INET AF_INET6" \
     ping -c1 -W1 192.168.1.1 >/dev/null 2>&1; then
  echo "ping con le restrizioni dell'unità: ok"
else
  echo "ATTENZIONE: con le restrizioni dell'unità il ping fallisce;" \
       "ping_group_range = $(sysctl -n net.ipv4.ping_group_range 2>/dev/null)." >&2
  echo "rb-link registrerà ERR (dato mancante), non KO." >&2
  ESITO=2
fi

for u in $UNITA; do
  echo "$u: $(systemctl is-active "$u" || true)"
done
exit $ESITO
