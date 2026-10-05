set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
original="${MINIDBMS_REPOSITORY:-$(CDPATH= cd -- "$script_dir/../../.." && pwd)}"
audit_base="${MINIDBMS_AUDIT_DIR:-${TMPDIR:-/tmp}/minidbms-audit-20261004}"
audit_source="$audit_base/source"
audit_python="$audit_base/env/bin/python"
evidence="$original/docs/auditoria/evidencias"
export MPLCONFIGDIR="$audit_base/matplotlib"
export PLAYWRIGHT_BROWSERS_PATH="$audit_base/browsers"
cd "$audit_source"
set +e
"$audit_python" -m pytest -q -W error --basetemp "$audit_base/pytest-temp" -o cache_dir="$audit_base/pytest-cache" --junitxml="$evidence/pytest.xml" > "$evidence/pytest.log" 2>&1
printf 'pytest_exit=%s\n' "$?" > "$evidence/resultados_comandos.txt"
"$audit_python" -W error -m demos.transactions_demo > "$evidence/demo_threads.json" 2>&1
printf 'demo_exit=%s\n' "$?" >> "$evidence/resultados_comandos.txt"
cd "$audit_source/frontend"
npm run typecheck > "$evidence/frontend_typecheck.log" 2>&1
printf 'typecheck_exit=%s\n' "$?" >> "$evidence/resultados_comandos.txt"
npm test > "$evidence/frontend_tests.log" 2>&1
printf 'frontend_tests_exit=%s\n' "$?" >> "$evidence/resultados_comandos.txt"
npm run build > "$evidence/frontend_build.log" 2>&1
printf 'build_exit=%s\n' "$?" >> "$evidence/resultados_comandos.txt"
cd "$audit_source"
"$audit_python" scripts/integration_check.py --data-dir "$audit_base/http-data" --port 18765 --report "$evidence/integracion_http.json" > "$evidence/integracion_http.log" 2>&1
printf 'integration_exit=%s\n' "$?" >> "$evidence/resultados_comandos.txt"
"$audit_python" -m playwright install chromium > "$evidence/playwright_install.log" 2>&1
printf 'browser_install_exit=%s\n' "$?" >> "$evidence/resultados_comandos.txt"
"$audit_python" "$original/scripts/sanitize_evidence.py" "$evidence"/*.log "$evidence/pytest.xml"
cat "$evidence/resultados_comandos.txt"
