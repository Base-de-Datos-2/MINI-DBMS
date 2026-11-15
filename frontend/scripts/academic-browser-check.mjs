import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { chromium, expect } from "playwright/test";

const [base = "http://127.0.0.1:8000"] = process.argv.slice(2).filter((arg) => arg !== "--live");
const live = process.argv.includes("--live");
const output = process.env.P5_SCREENSHOT_DIR;
const path = "/parte5/api/rag/ask";
const supported = "How does HNSW use a hierarchy of proximity graphs?";
const unrelated = "How do I change the oil in a 2015 Toyota Corolla?";
const noMatch = "zqxacademicnonmatch2026";
const markup = '<img src="invalid" onerror="alert(1)">';

const browser = await chromium.launch({ executablePath: process.env.BROWSER_EXECUTABLE_PATH });
try {
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
  const requests = [];
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.url().endsWith("/api/rag/ask")) {
      requests.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() });
      assert.equal(request.headers().authorization, undefined);
      assert.equal(request.headers()["x-session-token"], undefined);
    }
  });

  await page.goto(`${base}/#parte5`);
  const chat = page.getByRole("region", { name: "Consulta los papers" });
  const field = chat.getByLabel("Pregunta");
  const submit = chat.getByRole("button", { name: "Preguntar" });
  await expect(chat).toBeVisible();
  await expect(submit).toBeDisabled();
  await field.fill("   ");
  await expect(submit).toBeDisabled();

  async function ask(question, onPending = async () => {}) {
    await field.fill(question);
    const sent = page.waitForResponse((response) =>
      new URL(response.url()).pathname === path && response.request().method() === "POST",
      { timeout: 120_000 });
    await submit.click();
    await onPending();
    return sent;
  }

  async function verifySources(exchange, sources) {
    const items = exchange.getByRole("list", { name: "Fuentes consultadas" }).getByRole("listitem");
    await expect(items).toHaveCount(sources.length);
    for (const [i, source] of sources.entries()) {
      const item = items.nth(i);
      await expect(item.locator("summary")).toContainText(`[${source.label}] ${source.title}`);
      await expect(item.locator("summary")).toContainText(`${source.authors} · ${source.year}`);
      await item.locator("summary").press("Enter");
      await expect(item.locator("details")).toHaveAttribute("open", "");
      assert.equal(await item.locator(".academic-source-text").textContent(), source.content);
    }
  }

  if (live) {
    for (const [question, expectedChunks] of [[supported, [1, 3, 5]], [unrelated, [143, 362, 325]]]) {
      const response = await ask(question);
      assert.equal(response.status(), 200);
      const answer = await response.json();
      assert.equal(answer.status, "answered");
      assert.deepEqual(answer.sources.map((source) => source.chunk_id), expectedChunks);
      const exchange = chat.locator("article").filter({ has: page.getByRole("heading", { name: question, exact: true }) });
      await expect(exchange.locator(".academic-answer")).toBeVisible();
      assert.equal(await exchange.locator(".academic-answer").textContent(), answer.answer);
      await verifySources(exchange, answer.sources);
      console.log(JSON.stringify({ question, requestId: response.headers()["x-request-id"], answer: answer.answer, chunks: expectedChunks }));
      if (question === supported && output) {
        await mkdir(output, { recursive: true });
        await chat.screenshot({ path: join(output, "academic-chat.png") });
      }
    }
  } else {
    let release;
    const pending = new Promise((resolve) => { release = resolve; });
    const sources = [{ label: "S1", paper_id: 1, chunk_id: 1, position: 1, title: "Academic paper",
      authors: "A. Author", year: 2018, content: markup, score: 10 }];
    const answer = `Passage [S1]\n${markup}`;
    await page.route(`**${path}`, async (route) => {
      const { question } = route.request().postDataJSON();
      if (question === supported) {
        await pending;
        await route.fulfill({ json: { status: "answered", answer, sources } });
      } else if (question === unrelated) {
        await route.fulfill({ status: 504, json: { error: { code: "RAG_PROVIDER_TIMEOUT",
          message: "The answer provider timed out.", request_id: "browser-timeout" } } });
      } else {
        await route.continue();
      }
    });

    try {
      await ask(`  ${supported}  `, async () => {
        await expect(chat.getByRole("status")).toContainText("preparando la respuesta");
        await expect(submit).toBeDisabled();
        await field.evaluate((textarea) => textarea.form.requestSubmit());
        await page.getByRole("tab", { name: "Parte 3 Texto" }).click();
        await expect(chat).toBeHidden();
        await page.getByRole("tab", { name: "Parte 5 RAG académico" }).click();
        await expect(submit).toBeDisabled();
        assert.deepEqual(requests, [{ path, body: { question: supported } }]);
        release();
      });
    } finally {
      release();
    }
    const exchange = chat.locator("article");
    await expect(exchange).toHaveCount(1);
    assert.equal(await exchange.locator(".academic-answer").textContent(), answer);
    await verifySources(exchange, sources);
    await expect(exchange.locator("img")).toHaveCount(0);
    assert.equal((await ask(unrelated)).status(), 504);
    await expect(chat.getByRole("alert")).toContainText("El proveedor tardó demasiado");
    await expect(chat.getByRole("alert")).toContainText("browser-timeout");
    await expect(field).toHaveValue(unrelated);
    await expect(submit).toBeEnabled();
  }

  const empty = await ask(noMatch);
  assert.equal(empty.status(), 200);
  const noContext = await empty.json();
  assert.equal(noContext.status, "no_context");
  assert.deepEqual(noContext.sources, []);
  const emptyExchange = chat.locator("article").filter({ has: page.getByRole("heading", { name: noMatch, exact: true }) });
  await expect(emptyExchange).toContainText("No se encontraron pasajes");
  await expect(emptyExchange.getByRole("list")).toHaveCount(0);
  await expect(chat.getByRole("alert")).toHaveCount(0);

  await page.getByRole("tab", { name: "Parte 3 Texto" }).click();
  await expect(chat).toBeHidden();
  const textTab = page.getByRole("tabpanel", { name: "Parte 3 Texto" });
  const sql = textTab.getByLabel("Editor SQL");
  const statement = "SELECT * FROM documentos LIMIT 3;";
  await expect(textTab).toBeVisible();
  await sql.fill(statement);
  await page.getByRole("tab", { name: "Parte 5 RAG académico" }).click();
  await expect(chat.locator("article")).toHaveCount(live ? 3 : 2);
  assert.deepEqual(requests, [supported, unrelated, noMatch].map((question) => ({ path, body: { question } })));

  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await chat.evaluate((panel) => panel.scrollWidth <= panel.clientWidth), true);
  await page.getByRole("tab", { name: "Parte 3 Texto" }).click();
  await expect(sql).toHaveValue(statement);
  assert.deepEqual(errors, []);
  console.log(`Academic chat browser check PASS (${live ? "real provider" : "controlled success and timeout"}, Chromium ${browser.version()})`);
} finally {
  await browser.close();
}
