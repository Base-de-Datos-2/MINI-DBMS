set -eu
original='/workspace/mini-dbms'
implementation='/local-user/.cache/minidbms-implementation-20261004'
audit='/local-user/.cache/minidbms-audit-20261004'
uv="$audit/bootstrap/bin/uv"
"$uv" venv --python "$audit/env/bin/python" "$implementation/env"
"$uv" pip sync --offline --python "$implementation/env/bin/python" "$original/docs/implementacion/evidencias/entorno_pruebas.txt"
"$uv" pip install --offline --python "$implementation/env/bin/python" --no-deps -e "$implementation/source"
"$implementation/env/bin/python" -I -c 'import engine; print(engine.__file__)'
