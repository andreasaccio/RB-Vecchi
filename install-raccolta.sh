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
PROGRAMMI="giornaliero.py rb-carica.py rb-plc.py rb-link.py stato_rete.py"
UNITA="rb-carica.service rb-plc.service rb-link.service"
# Riepilogo powerline per la dashboard: oneshot lanciato dal timer ogni 60 s.
RIEPILOGO="rb-stato-rete.service rb-stato-rete.timer"
JSON="$DATA_DIR/stato-rete.json"

# Un'unità transitoria con lo stesso nome avrebbe la precedenza sul file in /etc.
for u in $UNITA $RIEPILOGO; do
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
chmod 0755 "$INSTALL_DIR"/rb-*.py "$INSTALL_DIR/stato_rete.py"
for u in $UNITA $RIEPILOGO; do
  install -m 0644 "$SRC/$u" "/etc/systemd/system/$u"
done

systemctl daemon-reload
systemctl enable $UNITA rb-stato-rete.timer
AVVIO=$(date +%s)
systemctl restart $UNITA

echo
ESITO=0
if sudo -u "$SERVICE_USER" ping -c1 -W1 192.168.1.1 >/dev/null 2>&1; then
  echo "ping come $SERVICE_USER: ok"
else
  echo "ATTENZIONE: $SERVICE_USER non riesce a fare ping a 192.168.1.1" >&2
  ESITO=2
fi

# Verifica sull'unità vera: le righe che rb-link ha scritto dopo il riavvio.
# Nessun ERR ammesso nell'ultimo giro (ERR = ping non eseguibile nell'unità).
echo "attesa di due giri di rb-link..."
sleep 12
GIORNI=$(printf '%s\n%s\n' "$(date -d "@$AVVIO" +%F)" "$(date +%F)" | uniq)
ULTIMO=$(for g in $GIORNI; do
           f="$DATA_DIR/rb-link-$g.csv"
           if [ -r "$f" ]; then cat "$f"; fi
         done | awk -F, -v da="$AVVIO" '
  $1 ~ /^[0-9]+$/ && $1 >= da { r[$1] = r[$1] $3 " "; if ($1 > m) m = $1 }
  END { if (m) print m, r[m] }')
if [ -z "$ULTIMO" ]; then
  echo "ATTENZIONE: rb-link non ha scritto righe dopo il riavvio." >&2
  ESITO=2
else
  set -- $ULTIMO
  TS=$1; shift
  N_ERR=0
  for s in "$@"; do case $s in ERR) N_ERR=$((N_ERR+1)) ;; esac; done
  if [ "$N_ERR" -gt 0 ]; then
    echo "ATTENZIONE: rb-link, ultimo giro ($(date -d "@$TS" +%T)): $N_ERR ERR su $#." \
         "Il logger è cieco: ping non eseguibile nell'unità." >&2
    journalctl -u rb-link.service -n 15 --no-pager >&2 || true
    ESITO=2
  else
    echo "rb-link, ultimo giro ($(date -d "@$TS" +%T)): $* -> nessun ERR"
  fi
fi

# Riepilogo: un giro dell'unità vera, poi il JSON che ha scritto e il tempo.
if systemctl start rb-stato-rete.service; then
  t0=$(systemctl show rb-stato-rete.service -p ExecMainStartTimestampMonotonic --value)
  t1=$(systemctl show rb-stato-rete.service -p ExecMainExitTimestampMonotonic --value)
  echo "riepilogo powerline calcolato in $(( (t1 - t0) / 1000 )) ms"
  sed -n 's/^ *"\(stato\|motivo\)": \(.*\),$/  \1: \2/p' "$JSON"
else
  echo "ATTENZIONE: rb-stato-rete.service non ha scritto $JSON" >&2
  journalctl -u rb-stato-rete.service -n 15 --no-pager >&2 || true
  ESITO=2
fi
systemctl restart rb-stato-rete.timer

for u in $UNITA rb-stato-rete.timer; do
  echo "$u: $(systemctl is-active "$u" || true)"
done
exit $ESITO
