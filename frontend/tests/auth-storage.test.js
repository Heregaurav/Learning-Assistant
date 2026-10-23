import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src");
const readSource = (relativePath) => readFile(path.join(root, relativePath), "utf8");

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(fullPath);
    return /\.(ts|tsx|js|jsx)$/.test(entry.name) ? [fullPath] : [];
  }));
  return nested.flat();
}

test("session and CSRF credentials are never read from or written to browser storage", async () => {
  const files = await sourceFiles(root);
  const storageCalls = /(?:localStorage|sessionStorage)\.(?:getItem|setItem)\s*\(\s*["'`]([^"'`]+)["'`]/g;
  const forbiddenKeys = new Set([
    "curiosity.csrf-token",
    "curiosity.guest-id",
    "curiosity.session-id",
    "curiosity.session",
  ]);

  for (const file of files) {
    const source = await readFile(file, "utf8");
    for (const match of source.matchAll(storageCalls)) {
      assert.equal(
        forbiddenKeys.has(match[1]),
        false,
        `${path.relative(root, file)} persists or reads auth key ${match[1]}`,
      );
    }
  }
});

test("known legacy auth keys are only removed, while unrelated preferences stay intact", async () => {
  const app = await readSource("App.tsx");
  assert.match(app, /localStorage\.removeItem\("curiosity\.csrf-token"\)/);
  assert.match(app, /localStorage\.removeItem\("curiosity\.guest-id"\)/);
  assert.match(app, /localStorage\.getItem\(THEME_KEY\)/);
  assert.match(app, /localStorage\.setItem\(THEME_KEY, next\)/);
  assert.match(app, /localStorage\.removeItem\("curiosity\.active-lesson"\)/);
});

test("refresh, Google login, and guest login restore CSRF only in runtime memory", async () => {
  const api = await readSource("lib/api.ts");
  assert.match(api, /let csrfToken = ""/);
  assert.match(api, /googleAuth[\s\S]*?setCsrfToken\(result\.csrfToken\)/);
  assert.match(api, /createGuestSession[\s\S]*?setCsrfToken\(result\.csrfToken\)/);
  assert.match(api, /getAuthSession[\s\S]*?result\.authenticated && result\.csrfToken\) setCsrfToken\(result\.csrfToken\)/);
  assert.match(api, /export const logout[\s\S]*?clearCsrfToken\(\)/);
});

test("cookie requests send the in-memory CSRF token through the existing header", async () => {
  const api = await readSource("lib/api.ts");
  assert.match(api, /credentials: "include"/);
  assert.match(api, /"X-CSRF-Token": csrfToken/);
  assert.doesNotMatch(api, /X-Guest-ID/);
});
