#!/bin/sh
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${OVERNIGHT_PYTHON:-$ROOT/.venv/bin/python}"
cd "$ROOT"
exec "$PY" -B -m tools.overnight.run_one --root "$ROOT" run "18"
