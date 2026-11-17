// Run against the unified server with all five parts prepared.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "playwright";

const base = process.argv[2] ?? "http://127.0.0.1:8000";
const output = process.argv[3] ?? "viewport-previews";
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
try {
  for (const [name, width, height] of [["desktop", 1440, 900], ["mobile", 390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height }, reducedMotion: "reduce" });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(base);
    for (let number = 1; number <= 5; number++) {
      const tab = page.locator(`#tab-parte${number}`);
      await tab.click();
      const panel = page.locator(`#panel-parte${number}`);
      await panel.locator(".sql-editor").waitFor();
      assert.equal(await tab.getAttribute("aria-selected"), "true");
      assert.equal(await page.locator(".part-panel:visible").count(), 1);
      assert.equal(await panel.locator(".load-error").count(), 0);
      if (number === 5) await panel.locator(".academic-form textarea").waitFor();
      await page.screenshot({ path: join(output, `${name}-parte${number}.png`) });
    }
    assert.deepEqual(errors, []);
    await page.close();
  }
} finally {
  await browser.close();
}
