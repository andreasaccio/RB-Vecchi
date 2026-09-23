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
