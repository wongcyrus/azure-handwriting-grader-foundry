import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import type { APIRequestContext, Page } from "@playwright/test";
import { expect } from "@playwright/test";

export const FAKE_TOKEN = "synthetic-canvas-e2e-only-not-a-real-credential";
export const API_BASE = "http://127.0.0.1:18765";
export const authHeaders = { Authorization: `Bearer ${FAKE_TOKEN}` };

export function seedExam(): string {
  const output = execFileSync(
    "uv",
    [
      "run",
      "--frozen",
      "--extra",
      "dev",
      "--extra",
      "engine",
      "python",
      "tools/seed_canvas.py",
      "--base-url",
      API_BASE,
    ],
    {
      cwd: resolve(import.meta.dirname, "../../.."),
      env: { ...process.env, FOUNDRY_DEV_TOKEN: FAKE_TOKEN },
      encoding: "utf-8",
    },
  );
  const { exam_id } = JSON.parse(output) as { exam_id: string };
  return exam_id;
}

export async function openExam(page: Page): Promise<string> {
  const exam_id = seedExam();
  await page.goto("/");
  await page.getByLabel("Exam ID", { exact: true }).fill(exam_id);
  await page.getByLabel("Synthetic development token").fill(FAKE_TOKEN);
  await page.getByRole("button", { name: "Load exam" }).click();
  await page.getByRole("button", { name: "Prepare template" }).click();
  await expect(
    page.getByLabel("I reviewed page 1 and its boxes"),
  ).toBeEnabled();
  return exam_id;
}

export async function currentExam(request: APIRequestContext, id: string) {
  const response = await request.get(`${API_BASE}/api/exams/${id}`, {
    headers: authHeaders,
  });
  expect(response.ok()).toBeTruthy();
  return { document: await response.json(), etag: response.headers()["etag"] };
}

export async function addBox(page: Page, label: string) {
  await page.getByLabel("New box label").selectOption(label);
  await page.getByRole("button", { name: "Add box with keyboard" }).click();
}
