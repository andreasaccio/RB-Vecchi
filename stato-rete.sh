#!/bin/sh
# Stato della rete (ultime 24 ore e 7 giorni) dai CSV di /var/lib/rb-raccolta.
# SOLA LETTURA. Opzioni: --finestra 24h|7g, --dir DIRECTORY, --ora EPOCH.
REPO=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -B "$REPO/raccolta/stato_rete.py" "$@"
