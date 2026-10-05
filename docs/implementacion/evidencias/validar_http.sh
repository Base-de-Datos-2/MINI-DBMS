set -eu
original='/workspace/mini-dbms'
implementation='/local-user/.cache/minidbms-implementation-20261004'
python='/local-user/.cache/minidbms-implementation-20261004/env/bin/python'
cp -a "$original/api" "$original/engine" "$original/scripts" "$implementation/source/"
cd "$implementation/source"
export PYTHONPATH="$PWD"
"$python" scripts/integration_check.py --backend-only --data-dir "$implementation/http-launcher" --port 18810 --report "$original/docs/implementacion/evidencias/launcher_http.json" > "$original/docs/implementacion/evidencias/launcher_http.log" 2>&1
tail -n 26 "$original/docs/implementacion/evidencias/launcher_http.log"
