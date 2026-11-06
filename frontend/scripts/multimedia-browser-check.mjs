// Part 4 real-browser check. Start `python -m api --multimedia` first, then from frontend/:
//   node scripts/multimedia-browser-check.mjs http://127.0.0.1:8000 <screenshot-dir>
import { chromium } from "playwright";
const base = process.argv[2], out = process.argv[3];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const report = { checks: [] };
await page.goto(base);
await page.waitForSelector('select[aria-label="Presets"] option:nth-child(2)', { state: 'attached' });
const presets = page.locator('select[aria-label="Presets"]');
async function run(label) {
  await presets.selectOption({ label });
  await page.getByRole("button", { name: "Ejecutar" }).click();
  await page.waitForSelector(".result-table tbody tr, .results-panel .status-block", { timeout: 20000 });
  await page.waitForTimeout(800);
}
await run("Imágenes similares (PDF)");
const thumbs = await page.$$eval(".result-table img.media-thumb", (els) => els.map((e) => [e.getAttribute("src"), e.complete && e.naturalWidth > 0]));
const queryImage = await page.$eval(".media-query img", (e) => e.complete && e.naturalWidth > 0).catch(() => false);
const planText = await page.locator(".plan-panel, [aria-labelledby='plan-title']").first().innerText().catch(() => "");
report.checks.push({ query: "images", rows: thumbs.length, all_loaded: thumbs.every((t) => t[1]), query_image_loaded: queryImage,
  plan_mentions_vector: planText.includes("VectorIndexScan"), plan_mentions_hnsw: planText.includes("HNSW") });
await page.screenshot({ path: `${out}/ui_images.png`, fullPage: true });
await run("Canciones similares (PDF)");
await run("Canciones con reproductor");
const audios = await page.$$eval(".result-table audio", (els) => els.map((e) => e.getAttribute("src")));
const headers = await page.$$eval(".result-table th", (els) => els.map((e) => e.textContent));
const planAudio = await page.locator(".plan-panel, [aria-labelledby='plan-title']").first().innerText().catch(() => "");
report.checks.push({ query: "audio", players: audios.length, headers, plan_mentions_ivf: planAudio.includes("IVF"),
  note_visible: (await page.locator(".media-query").innerText()).includes("−distancia") });
await page.screenshot({ path: `${out}/ui_audio.png`, fullPage: true });
await page.getByLabel("Usar índices").uncheck();
await run("Misma consulta con IVF");
const planScan = await page.locator(".plan-panel, [aria-labelledby='plan-title']").first().innerText().catch(() => "");
report.checks.push({ query: "scan toggle", plan_mentions_vectorscan: planScan.includes("VectorScan"), plan_mentions_requested: planScan.includes("requested IVF") });
const status = await fetch(`${base}/api/multimedia/imagenes/media/..%2Fcollection.json`).then((r) => r.status);
report.checks.push({ traversal_status: status });
report.browser = browser.version();
console.log(JSON.stringify(report, null, 2));
await browser.close();
