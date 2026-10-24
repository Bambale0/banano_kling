import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright";
// Browser side effects mocked; real paid contract evidence in docs/kling4-live-smoke.json.
const port = Number(process.env.KLING4_E2E_PORT || 4206),
  origin = `http://127.0.0.1:${port}`,
  base = origin + "/mini-app/";
const root = mkdtempSync(join(tmpdir(), "kling4-browser-"));
symlinkSync(resolve("out"), join(root, "mini-app"), "dir");
const server = spawn(
  "python3",
  [
    "-m",
    "http.server",
    String(port),
    "--bind",
    "127.0.0.1",
    "--directory",
    root,
  ],
  { stdio: "ignore" },
);
const image = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a++sAAAAASUVORK5CYII=",
  "base64",
);
const model = {
  id: "kling_4",
  label: "Kling 4",
  description: "Админ",
  durations: [3, 5, 30],
  ratios: ["auto", "16:9"],
  supports: ["text", "imgtxt"],
  costs: {},
  quality_costs: {},
};
let browser;
async function setup(admin, width = 375, behavior = {}) {
  const context = await browser.newContext({
      viewport: { width, height: 840 },
    }),
    page = await context.newPage();
  page.setDefaultTimeout(12000);
  const errors = [],
    quotes = [],
    generations = [],
    uploads = new Map(),
    chunks = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => {
    window.Telegram = {
      WebApp: {
        initData: "query_id=kling4-browser-fixture",
        initDataUnsafe: {},
        ready() {},
        expand() {},
        onEvent() {},
        offEvent() {},
      },
    };
    const owners = new WeakMap();
    document.addEventListener(
      "change",
      (event) => {
        if (
          event.target instanceof HTMLInputElement &&
          event.target.type === "file"
        )
          for (const file of event.target.files || [])
            owners.set(file, event.target);
      },
      true,
    );
    for (const method of ["arrayBuffer", "slice"]) {
      const original = File.prototype[method];
      File.prototype[method] = function (...args) {
        const owner = owners.get(this);
        if (owner && !owner.value)
          throw new DOMException(
            "Native picker cleared before read",
            "NotReadableError",
          );
        return original.apply(this, args);
      };
    }
  });
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "owned.test")
      return route.fulfill({ contentType: "image/png", body: image });
    if (url.origin !== origin) return route.abort();
    if (!url.pathname.includes("/api/")) return route.continue();
    let body = {};
    try {
      body = route.request().postDataJSON() || {};
    } catch {}
    let result = { ok: true };
    if (url.pathname.endsWith("/bootstrap"))
      result = {
        ok: true,
        telegram_id: 424242,
        first_name: "Synthetic",
        credits: 1000,
        is_admin: admin,
        telegram_chat_available: true,
        bot_username: "synthetic_bot",
        mini_app_url: base,
        actions: [],
        payment_packages: [],
        recent_tasks: [],
        saved_references: [],
        image_models: [
          {
            id: "banana_pro",
            label: "Image",
            ratios: ["1:1"],
            cost: 2,
            max_references: 8,
          },
        ],
        video_models: admin
          ? [model]
          : [{ ...model, id: "v3_pro", label: "Kling 3.0", costs: { 5: 5 } }],
      };
    else if (url.pathname.endsWith("/kling4/media/init")) {
      uploads.set(body.upload_id, body);
      result = { ok: true, upload_id: body.upload_id };
    } else if (url.pathname.endsWith("/kling4/media/chunk"))
      chunks.push(route.request().postDataBuffer());
    else if (url.pathname.endsWith("/kling4/media/complete")) {
      const upload = uploads.get(body.upload_id);
      assert.ok(upload);
      result = { ok: true, url: "https://owned.test/" + upload.filename };
    } else if (url.pathname.endsWith("/kling4/media/import"))
      result = { ok: true, url: body.url };
    else if (url.pathname.endsWith("/kling4/media/cancel"))
      result = { ok: true };
    else if (url.pathname.endsWith("/kling4/history"))
      result = { ok: true, tasks: [] };
    else if (url.pathname.endsWith("/kling4/quote")) {
      assert.equal(generations.length, 0);
      quotes.push(body);
      result = {
        ok: true,
        quote_hash: "browser-quote",
        provider_credits: "85.5",
        rate: "28.5",
        billed_seconds: "3",
        input_video_seconds: "0",
        cost: 0,
      };
    } else if (url.pathname.endsWith("/kling4/generate")) {
      generations.push(body);
      if (behavior.dropFirst && generations.length === 1) return route.abort();
      result = {
        ok: true,
        task_id: "kling4_browser",
        status: "pending",
        result_url: null,
        actual_credits: null,
        quote: { provider_credits: "85.5" },
      };
    } else if (url.pathname.endsWith("/kling4/status"))
      result = {
        ok: true,
        task_id: "kling4_browser",
        status: "pending",
        result_url: null,
        actual_credits: null,
        quote: { provider_credits: "85.5" },
      };
    else if (/generate|payment|upload|kling4/.test(url.pathname))
      throw new Error("Unexpected mutation " + url.pathname);
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(result),
    });
  });
  await page.goto(base + "?tgWebAppData=query_id%3Dkling4-browser-fixture", {
    waitUntil: "networkidle",
  });
  await page.getByRole("button", { name: "Видео", exact: true }).click();
  return { context, page, errors, quotes, generations, chunks };
}
async function upload(page, label, name) {
  await page
    .getByLabel(label, { exact: true })
    .setInputFiles({ name, mimeType: "image/png", buffer: image });
  await page
    .getByRole("status")
    .filter({ hasText: "Загрузка" })
    .waitFor({ state: "hidden" });
}
try {
  const deadline = Date.now() + 20000;
  while (true) {
    try {
      if ((await fetch(base)).ok) break;
    } catch {}
    if (Date.now() > deadline) throw new Error("Static export unavailable");
    await new Promise((r) => setTimeout(r, 100));
  }
  browser = await chromium.launch({ headless: true });
  const qa = await setup(true),
    { page } = qa;
  await page.getByTestId("kling4-form").waitFor();
  await page.getByLabel("Промпт Kling 4").fill("A cinematic landscape");
  await page.getByLabel("Длительность Kling 4").fill("3");
  await upload(page, "Загрузить Референсы фото", "first.png");
  await page
    .getByRole("button", { name: "+ Элемент по фото", exact: true })
    .click();
  await page.getByLabel("Имя элемента 1").fill("Hero");
  await upload(page, "Загрузить Фото элемента 1 (2–4)", "hero-front.png");
  await upload(page, "Загрузить Фото элемента 1 (2–4)", "hero-side.png");
  await page.getByRole("button", { name: "@Hero", exact: true }).click();
  await page.getByLabel("Режим Kling 4").selectOption("keyframe");
  await upload(page, "Загрузить Первый кадр", "start.png");
  await upload(page, "Загрузить Промежуточные кадры", "middle-1.png");
  await upload(page, "Загрузить Промежуточные кадры", "middle-2.png");
  await page.getByLabel("Переместить Промежуточные кадры 2 вверх").click();
  await upload(page, "Загрузить Последний кадр", "end.png");
  await page.getByLabel("Режим Kling 4").selectOption("reference");
  assert.equal(await page.getByLabel("Имя элемента 1").inputValue(), "Hero");
  assert.equal(await page.locator('img[alt="Референсы фото 1"]').count(), 1);
  await page.getByLabel("Режим Kling 4").selectOption("keyframe");
  await page
    .getByLabel("Промпт Kling 4")
    .fill(
      "Start at @first_frame through @keyframe_1 and finish at @last_frame",
    );
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth + 1,
    ),
    false,
    "Mobile overflow",
  );
  await page
    .getByRole("button", { name: "Рассчитать Kling 4", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Подтвердить и создать", exact: true })
    .waitFor();
  await page.getByLabel("Разрешение Kling 4").selectOption("1080p");
  assert.equal(
    await page
      .getByRole("button", { name: "Подтвердить и создать", exact: true })
      .count(),
    0,
  );
  await page
    .getByRole("button", { name: "Рассчитать Kling 4", exact: true })
    .click();
  const start = page.getByRole("button", {
    name: "Подтвердить и создать",
    exact: true,
  });
  await start.scrollIntoViewIfNeeded();
  await start.click();
  assert.equal(qa.generations.length, 1);
  assert.deepEqual(qa.generations[0].recipe, qa.quotes.at(-1).recipe);
  assert.deepEqual(qa.generations[0].recipe.input.keyframe_urls, [
    "https://owned.test/middle-2.png",
    "https://owned.test/middle-1.png",
  ]);
  assert.ok(
    qa.chunks.every((chunk) => chunk.includes(image)),
    "Original bytes preserved",
  );
  assert.equal(await page.getByLabel("Промпт Kling 4").isDisabled(), true);
  assert.deepEqual(qa.errors, []);
  mkdirSync(".artifacts/kling4", { recursive: true });
  await page.screenshot({
    path: ".artifacts/kling4/mobile.png",
    fullPage: true,
  });
  await qa.context.close();
  const retry = await setup(true, 430, { dropFirst: true });
  await retry.page.getByLabel("Промпт Kling 4").fill("Network recovery scene");
  await retry.page
    .getByRole("button", { name: "Рассчитать Kling 4", exact: true })
    .click();
  await retry.page
    .getByRole("button", { name: "Подтвердить и создать", exact: true })
    .click();
  await retry.page
    .getByRole("button", {
      name: "Проверить запуск",
      exact: true,
    })
    .waitFor();
  assert.equal(
    await retry.page.getByLabel("Промпт Kling 4").isDisabled(),
    true,
  );
  await retry.page
    .getByRole("button", {
      name: "Проверить запуск",
      exact: true,
    })
    .click();
  assert.equal(retry.generations.length, 2);
  assert.equal(
    retry.generations[0].idempotency_key,
    retry.generations[1].idempotency_key,
  );
  assert.deepEqual(retry.generations[0].recipe, retry.generations[1].recipe);
  const visibleText = await retry.page.getByTestId("kling4-form").innerText();
  assert.doesNotMatch(visibleText, /KIE|credits|provider_task_id|Расход|pending|kling4_/);
  assert.deepEqual(retry.errors, []);
  await retry.context.close();
  const ordinary = await setup(false, 430);
  assert.equal(await ordinary.page.getByTestId("kling4-form").count(), 0);
  await ordinary.page.locator("button[aria-expanded]").first().click();
  assert.equal(
    await ordinary.page
      .getByRole("button", { name: "Kling 4", exact: true })
      .count(),
    0,
  );
  assert.equal(ordinary.generations.length, 0);
  assert.deepEqual(ordinary.errors, []);
  await ordinary.context.close();
  console.log(
    "PASS Kling4 Playwright: admin-only catalog, native original uploads, elements, preserved drafts, frame order, stale quote, one launch, pending lock,375/430px",
  );
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
  rmSync(root, { recursive: true, force: true });
}
