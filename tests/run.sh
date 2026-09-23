#!/usr/bin/env bash
# Ejecuta las pruebas en contenedores desechables SIN RED. Uso: tests/run.sh
set -u
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"
IMG="guarderia-monitor-tests"

echo "Construyendo la imagen de pruebas..."
docker build -q -t "$IMG" . >/dev/null || { echo "ERROR: docker build ha fallado"; exit 1; }

total_pass=0; fallidos=()
run() {  # run <fichero> [opciones de docker run...]
  local f="$1"; shift
  echo "=== $f"
  local out
  out=$(docker run --rm --network none -v "$REPO":/app:ro -e PYTHONDONTWRITEBYTECODE=1 \
        "$@" --entrypoint python "$IMG" "/app/tests/$f" 2>&1)
  echo "$out" | grep -E '^(PASS|FAIL)|Traceback'
  total_pass=$((total_pass + $(echo "$out" | grep -c '^PASS')))
  if echo "$out" | grep -qE '^FAIL|Traceback' || ! echo "$out" | grep -q '^PASS'; then
    fallidos+=("$f"); echo "$out" | tail -n 20
  fi
}

VIEJAS=(-e FICHAJE_HILO=0 -e TG_BOT_TOKEN=x -e TG_CHAT_ID=1 -e WL_USER=x -e WL_PASS=x)
run test_fichaje.py   "${VIEJAS[@]}"
run test_fichaje2.py  "${VIEJAS[@]}"
run test_fichaje3.py  "${VIEJAS[@]}"
run test_bot_unico.py
run test_hilo.py

echo
if [ ${#fallidos[@]} -eq 0 ]; then
  echo "OK: $total_pass pruebas pasadas, 0 fallos."
else
  echo "FALLOS en: ${fallidos[*]} ($total_pass pruebas pasadas)"; exit 1
fi
