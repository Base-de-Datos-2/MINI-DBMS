set -eu
original='/mnt/c/Users/Ian/Desktop/UTEC/TRABAJOS (PAGOS)/Paolo - BD2'
audit_base='/home/ian/.cache/minidbms-audit-20261004'
audit_source="$audit_base/source"
audit_env="$audit_base/env"
mkdir -p "$audit_base"
python3 -m pip install --target "$audit_base/bootstrap" uv
export UV_PYTHON_INSTALL_DIR="$audit_base/python"
"$audit_base/bootstrap/bin/uv" python install 3.11.9
"$audit_base/bootstrap/bin/uv" venv --python 3.11.9 "$audit_env"
mkdir -p "$audit_source"
git -C "$original" archive HEAD | tar -x -C "$audit_source"
cp "$original/Proyecto_Final.pdf" "$audit_source/Proyecto_Final.pdf"
mkdir -p "$audit_source/audit-results"
export MPLCONFIGDIR="$audit_base/matplotlib"
"$audit_base/bootstrap/bin/uv" pip install --python "$audit_env/bin/python" -e "$audit_source[test,api,bench]" playwright
cd "$audit_source/frontend"
npm ci --no-audit --no-fund
cd "$audit_source"
"$audit_env/bin/python" --version
"$audit_env/bin/python" -m pip --version || true
"$audit_env/bin/python" -c 'import importlib.metadata as m; print({n:m.version(n) for n in ["pytest","fastapi","starlette","uvicorn","httpx2","anyio","matplotlib","playwright"]})'
node --version
npm --version
