import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect
from scripts.setup_demo import prepare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18766)
    args = parser.parse_args()
    evidence = args.evidence
    prepare(args.data, reset=False)
    log = (evidence / 'servidor_navegador.log').open('w')
    process = subprocess.Popen([sys.executable, '-m', 'api', '--allow-writes',
                                '--data-dir', str(args.data), '--port', str(args.port)],
                               stdout=log, stderr=subprocess.STDOUT)
    checks = []
    base = f'http://127.0.0.1:{args.port}'

    def check(name, passed, details=''):
        checks.append(dict(name=name, passed=bool(passed), details=details))

    try:
        for _ in range(100):
            try:
                with urlopen(base + '/api/health', timeout=2) as response:
                    if json.load(response)['status'] == 'ready':
                        break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError('Server exited before health became ready')
                time.sleep(.1)
        else:
            raise TimeoutError('Server health did not become ready')
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1500, 'height': 1000})
            a, b = context.new_page(), context.new_page()
            errors = []
            a.on('pageerror', lambda error: errors.append(str(error)))
            for page in (a, b):
                page.goto(base + '/')
                expect(page.get_by_role('group', name='Sesión y transacción')).to_be_visible()
                expect(page.locator('.files-panel')).to_contain_text('students')
            check('four_panels', all(a.locator(selector).count() == 1 for selector in
                  ['.files-panel', '.query-panel', '.results-panel', '.plan-panel']))
            check('table_schema', 'INTEGER' in a.locator('.files-panel').inner_text())

            def run(page, sql):
                page.get_by_role('textbox', name='Editor SQL').fill(sql)
                with page.expect_response(lambda response: response.url.endswith('/api/query')) as info:
                    page.get_by_role('button', name='Ejecutar', exact=True).click()
                body = info.value.json()
                expect(page.get_by_role('button', name='Ejecutar', exact=True)).to_be_enabled()
                return body

            result = run(a, 'SELECT * FROM students WHERE id = 3')
            expect(a.locator('.plan-panel')).to_contain_text('IndexScan')
            check('indexed_results', result.get('rows') is not None and
                  'students_id_hash' in a.locator('.plan-panel').inner_text(), result.get('rows'))
            a.get_by_role('checkbox', name='Usar índices').uncheck()
            baseline = run(a, 'SELECT * FROM students WHERE id = 3')
            expect(a.locator('.plan-panel')).to_contain_text('TableScan')
            check('index_scan_same_results', baseline.get('rows') == result.get('rows'))
            invalid = run(a, 'SELECT FROM students')
            expect(a.get_by_role('alert')).to_be_visible()
            check('controlled_error', 'error' in invalid and 'Línea' in a.locator('.query-panel').inner_text())
            recovered = run(a, 'SELECT name FROM students ORDER BY name')
            expect(a.locator('.plan-panel')).to_contain_text('ExternalSort')
            check('recovery_and_sort', 'error' not in recovered)
            a.get_by_role('button', name='BEGIN', exact=True).click()
            expect(a.get_by_role('button', name='END', exact=True)).to_be_enabled()
            inserted = run(a, "INSERT INTO enrollments VALUES (9001, 'AUDIT')")
            check('provisional_insert', inserted.get('transaction', {}).get('provisional') is True)
            b.get_by_role('textbox', name='Editor SQL').fill('SELECT COUNT(*) AS n FROM enrollments')
            with b.expect_response(lambda response: response.url.endswith('/api/query')) as pending:
                b.get_by_role('button', name='Ejecutar', exact=True).click()
                expect(b.locator('.session-bar')).to_contain_text('Esperando lock', timeout=5000)
                check('concurrent_lock_visible', True)
                a.get_by_role('button', name='END', exact=True).click()
            completed = pending.value.json()
            expect(b.get_by_role('button', name='Ejecutar', exact=True)).to_be_enabled()
            check('commit_unblocks_reader', completed.get('rows') == [[5]], completed.get('rows'))
            a.get_by_role('button', name='BEGIN', exact=True).click()
            expect(a.get_by_role('button', name='ROLLBACK', exact=True)).to_be_enabled()
            run(a, "INSERT INTO enrollments VALUES (9002, 'ROLLBACK')")
            a.get_by_role('button', name='ROLLBACK', exact=True).click()
            expect(a.get_by_role('button', name='BEGIN', exact=True)).to_be_enabled()
            rollback = run(a, 'SELECT * FROM enrollments WHERE student_id = 9002')
            check('rollback_removes_row', rollback.get('rows') == [])
            check('no_browser_errors', not errors, errors)
            a.screenshot(path=str(evidence / 'navegador.png'), full_page=True)
            (evidence / 'navegador_dom.html').write_text(a.content(), encoding='utf-8')
            browser.close()
    except Exception as error:
        check('harness_exception', False, repr(error))
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)
        log.close()
        document = dict(checks=checks, passed=sum(c['passed'] for c in checks),
                        total=len(checks), server_exit=process.returncode)
        (evidence / 'navegador.json').write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps(document, ensure_ascii=False))
    return 0 if all(c['passed'] for c in checks) else 1


if __name__ == '__main__':
    raise SystemExit(main())
