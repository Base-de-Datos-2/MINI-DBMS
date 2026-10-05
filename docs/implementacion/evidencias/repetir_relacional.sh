set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
original="${MINIDBMS_REPOSITORY:-$(CDPATH= cd -- "$script_dir/../../.." && pwd)}"
implementation="${MINIDBMS_IMPLEMENTATION_DIR:-${TMPDIR:-/tmp}/minidbms-implementation-20261004}"
python="$implementation/env/bin/python"
cd "$implementation/source"
export PYTHONPATH="$PWD"
source_commit=$(git -C "$original" rev-parse HEAD)
run_dir=$(mktemp -d "$implementation/relational-first-delivery-XXXXXX")
"$python" "$original/docs/implementacion/evidencias/repetir_relacional.py" \
    --output "$run_dir/results" --workdir "$run_dir/work" \
    --figures "$original/docs/experimentos/actualizados_1k_10k" \
    --source-commit "$source_commit" \
    > "$original/docs/implementacion/evidencias/relacional_repeticion.log" 2>&1
destination="$original/benchmarks/results/relational/2026-10-04"
test ! -e "$destination"
mkdir -p "$destination"
cp -a "$run_dir/results/." "$destination/"
cp "$original/docs/implementacion/evidencias/repetir_relacional.py" "$destination/driver.py"
"$python" "$original/scripts/sanitize_evidence.py" "$original/docs/implementacion/evidencias/relacional_repeticion.log" "$original/docs/experimentos/actualizados_1k_10k/resultados.md"
tail -n 25 "$original/docs/implementacion/evidencias/relacional_repeticion.log"
