#!/bin/sh
# Confronta /opt/rb-vecchi con il repository e mostra da dove gira il servizio.
REPO=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
n=0
for f in $(cd /opt/rb-vecchi && find . -path ./venv -prune -o -type f -print); do
  cmp -s "/opt/rb-vecchi/$f" "$REPO/$f" || { echo "DIFF $f"; n=$((n+1)); }
done
[ "$n" -eq 0 ] && echo "produzione allineata al repository"
cd "$REPO" && echo "commit: $(git log --oneline -1 --decorate)"
echo "servizio: $(systemctl show rb-vecchi -p ExecMainStatus -p ActiveState --value | tr '\n' ' ')"
echo "workdir : $(systemctl show rb-vecchi -p WorkingDirectory --value)"
sleep 2
echo "healthz : $(curl -s --max-time 4 http://127.0.0.1:8080/healthz || echo 'NESSUNA RISPOSTA')"

# Raccolta dati: /opt/rb-raccolta e unità contro raccolta/ del repository.
m=0
if [ -d /opt/rb-raccolta ]; then
  for f in $(cd /opt/rb-raccolta && find . -name __pycache__ -prune -o -type f -print); do
    cmp -s "/opt/rb-raccolta/$f" "$REPO/raccolta/$f" || { echo "DIFF raccolta/$f"; m=$((m+1)); }
  done
else
  echo "MANCA /opt/rb-raccolta"; m=$((m+1))
fi
for u in rb-carica rb-plc rb-link; do
  if [ ! -e "/etc/systemd/system/$u.service" ]; then
    echo "MANCA /etc/systemd/system/$u.service"; m=$((m+1))
  elif ! cmp -s "/etc/systemd/system/$u.service" "$REPO/raccolta/$u.service"; then
    echo "DIFF $u.service"; m=$((m+1))
  fi
done
[ "$m" -eq 0 ] && echo "raccolta allineata al repository"
# Per ogni raccoglitore: stato dell'unità, età e stato dell'ultima riga (per
# rb-plc l'ultimo campione di ogni adattatore, per rb-link l'ultimo giro).
DATI=${RB_RACCOLTA_DIR:-/var/lib/rb-raccolta}
OGGI=$(date +%F)
ADESSO=$(date +%s)
for u in rb-carica rb-plc rb-link; do
  f=$DATI/$u-$OGGI.csv
  attivo=$(systemctl show "$u" -p ActiveState --value)
  if [ ! -s "$f" ]; then
    printf '%-9s: %s, nessun file di oggi\n' "$u" "$attivo"
    continue
  fi
  ts=$(tail -n 1 "$f" | cut -d, -f1)
  case $ts in
    ts) printf '%-9s: %s, solo intestazione\n' "$u" "$attivo"; continue ;;
    ''|*[!0-9]*) printf '%-9s: %s, ultima riga non valida\n' "$u" "$attivo"; continue ;;
  esac
  case $u in
    rb-carica) stato=$(tail -n 1 "$f" | cut -d, -f2,3 | tr , " ") ;;
    rb-plc) stato=$(tail -n 20 "$f" | awk -F, '$1 ~ /^[0-9]+$/ { s[$2] = $3 (($3 == "ok") ? "" : " " $4) }
                    END { for (a in s) printf "%s%s %s", (n++ ? ", " : ""), a, s[a] }') ;;
    rb-link) stato=$(tail -n 20 "$f" | awk -F, -v t="$ts" '$1 == t { c[$3]++ }
                     END { printf "ok %d, KO %d, ERR %d", c["ok"], c["KO"], c["ERR"] }') ;;
  esac
  printf '%-9s: %s, ultima riga %d s fa, %s\n' "$u" "$attivo" "$((ADESSO - ts))" "$stato"
  case $u:$stato in
    rb-link:*"ERR 0") ;;
    rb-link:*)
      echo "!!! rb-link: l'ultimo giro contiene ERR, ping non eseguibile: il logger è CIECO"
      echo "!!! vedi: journalctl -u rb-link -n 20" ;;
  esac
done
