// Real server + browser acceptance. No API mocks or fabricated ranking results.
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const python = process.env.PYTHON_EXECUTABLE || 'python';
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'mini-dbms-text-'));
const directory = path.join(work, 'database');
const first = "SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10;";
const second = "SELECT *, SCORE() as relevancia FROM articulos WHERE MATCH(texto, 'machine learning') USING BM25 ORDER BY relevancia DESC;";
const checks = [];
let server, browser, url;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function stop() {
  if (!server || server.exitCode !== null) return;
  const child = server;
  child.kill('SIGINT');
  await Promise.race([new Promise(resolve => child.once('exit', resolve)), pause(7000)]);
  if (child.exitCode === null) { child.kill('SIGKILL'); throw new Error('Server shutdown timed out'); }
  assert.equal(child.exitCode, 0);
  server = null;
}
async function freePort() {
  const probe = net.createServer();
  await new Promise(resolve => probe.listen(0, '127.0.0.1', resolve));
  const port = probe.address().port;
  await new Promise(resolve => probe.close(resolve));
  return port;
}
async function start() {
  const port = await freePort(); url = `http://127.0.0.1:${port}`;
  server = spawn(python, ['-m', 'api', '--text', '--allow-writes', '--data-dir', directory,
    '--port', String(port)], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  let log = ''; server.stdout.on('data', chunk => log += chunk); server.stderr.on('data', chunk => log += chunk);
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw new Error(log);
    try { if ((await fetch(url + '/api/health')).ok) return; } catch {}
    await pause(100);
  }
  throw new Error('Server did not start: ' + log);
}
async function sql(page, statement, indexed = true) {
  await page.getByLabel('Editor SQL', { exact: true }).fill(statement);
  await page.getByLabel('Usar índices', { exact: true }).setChecked(indexed);
  const reply = page.waitForResponse(response => response.url().endsWith('/api/query') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Ejecutar', exact: true }).click();
  const response = await reply, body = await response.json();
  assert.equal(response.status(), 200, JSON.stringify(body));
  await page.locator('.query-panel').getByRole('button', { name: 'Ejecutar', exact: true }).waitFor();
  await page.waitForFunction(() => document.querySelector('.results-panel')?.getAttribute('aria-busy') === 'false');
  return body;
}
(async () => {
  const prepared = spawnSync(python, ['scripts/setup_text.py', '--data-dir', directory], { cwd: root, encoding: 'utf8' });
  assert.equal(prepared.status, 0, prepared.stderr || prepared.stdout);
  checks.push('offline preparation, publication and fresh owner validation');
  await start();
  browser = await chromium.launch({ headless: true,
    executablePath: process.env.BROWSER_EXECUTABLE_PATH || undefined,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--use-gl=angle', '--use-angle=swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
  const errors = []; page.on('pageerror', error => { errors.push(error.message); console.error('Browser:', error.message); });
  await page.goto(url);
  await page.getByLabel('Colección textual', { exact: true }).selectOption('documentos');
  await page.getByLabel('Consulta textual', { exact: true }).fill('base datos');
  const panel = page.locator('#text-title');
  const panelSearch = async () => {
    const pending = page.waitForResponse(response => response.url().endsWith('/api/text/query') && response.request().method() === 'POST');
    await panel.getByRole('button', { name: 'Buscar', exact: true }).click();
    const response = await pending, body = await response.json();
    assert.equal(response.status(), 200, JSON.stringify(body));
    await panel.locator('tbody tr').first().waitFor();
    assert.equal(await panel.locator('tbody tr').count(), body.rows.length);
    assert((await panel.innerText()).includes(body.model));
    assert((await panel.innerText()).includes(body.plan.operator));
    return body;
  };
  const ranked = await panelSearch(); assert(ranked.rows.length > 0);
  await panel.getByLabel('Usar índice', { exact: true }).uncheck();
  const scanned = await panelSearch(); assert.deepEqual(scanned.rows, ranked.rows);
  checks.push('panel BM25 index/scan equivalence, rows, score/model/operator visible');
  await panel.getByLabel('Modelo textual').selectOption('TF_IDF');
  await panelSearch(); checks.push('panel TF-IDF scan');
  await panel.getByRole('button', { name: 'Enviar SQL al editor' }).click();
  assert((await page.getByLabel('Editor SQL', { exact: true }).inputValue()).includes('USING TF_IDF'));
  const a = await sql(page, first), b = await sql(page, second);
  assert(a.rows.length > 0 && b.rows.length > 0);
  assert(await page.locator('.results-panel tbody tr').count() > 0);
  assert((await page.locator('.plan-panel').innerText()).includes('TextIndexScan'));
  checks.push('both literal PDF queries via editor; results and native plan visible');
  const scan = await sql(page, second, false); assert.deepEqual(scan.rows, b.rows);
  assert((await page.locator('.plan-panel').innerText()).includes('TextScan'));
  const explained = await sql(page, 'EXPLAIN ' + second);
  assert.equal(explained.plan_status, 'prepared');
  const analyzed = await sql(page, 'EXPLAIN ANALYZE ' + second);
  assert.equal(analyzed.plan_status, 'execution-observed');
  checks.push('SQL scan equivalence, EXPLAIN and measured EXPLAIN ANALYZE');
  await page.locator('.files-panel .table-button').filter({ hasText: 'documentos' }).click();
  await page.getByText('documentos_spimi', { exact: true }).waitFor();
  checks.push('Files panel displays SPIMI metadata');
  const tokens = await Promise.all([1, 2].map(async () => (await (await fetch(url + '/api/sessions', { method: 'POST' })).json()).token));
  const concurrent = await Promise.all(tokens.map(async token => {
    const response = await fetch(url + '/api/query', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session-Token': token }, body: JSON.stringify({ sql: second }) });
    assert.equal(response.status, 200); return (await response.json()).rows;
  }));
  assert.deepEqual(concurrent[0], concurrent[1]);
  const blocked = await fetch(url + '/api/query', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sql: "INSERT INTO documentos VALUES (999, 'blocked')" }) });
  assert(blocked.status >= 400);
  checks.push('real concurrent HTTP readers and persistent write rejection with allow-writes');
  await stop(); await start(); await page.goto(url);
  const reopenedA = await sql(page, first), reopenedB = await sql(page, second);
  assert.deepEqual(reopenedA.rows, a.rows); assert.deepEqual(reopenedB.rows, b.rows);
  checks.push('fresh server restart preserves exact documents, order and scores');
  assert.deepEqual(errors, []);
  const report = { status: 'PASS', checks, browser: browser.version(), screenshots: 'not included' };
  const output = process.env.REPORT_PATH || path.join(work, 'text-browser-results.json');
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));
})().catch(error => { console.error(error.stack); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  await stop();
});
