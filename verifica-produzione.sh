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
OGGI=$(date +%F)
ADESSO=$(date +%s)
for u in rb-carica rb-plc rb-link; do
  f=/var/lib/rb-raccolta/$u-$OGGI.csv
  if [ -s "$f" ]; then
    ts=$(tail -n 1 "$f" | cut -d, -f1)
    case $ts in
      ts) eta="solo intestazione" ;;
      ''|*[!0-9]*) eta="ultima riga non valida" ;;
      *) eta="ultima riga $((ADESSO - ts)) s fa" ;;
    esac
  else
    eta="nessun file di oggi"
  fi
  printf '%-9s: %s, %s\n' "$u" "$(systemctl show "$u" -p ActiveState --value)" "$eta"
done
