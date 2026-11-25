import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import {
  API_BASE,
  FAKE_TOKEN,
  authHeaders,
  currentExam,
  seedExam,
} from "./support";

const keyErrors = new WeakMap<Page, string[]>();
test.beforeEach(({ page }) => {
  const errors: string[] = [];
  keyErrors.set(page, errors);
  page.on("console", (message) => {
    if (message.type() === "error" && message.text().includes("same key"))
      errors.push(message.text());
  });
});
test.afterEach(({ page }) => {
  expect(keyErrors.get(page)).toEqual([]);
});

async function openChecks(page: Page, id: string) {
  await page.goto("/");
  await page.getByLabel("Exam ID", { exact: true }).fill(id);
  await page.getByLabel("Synthetic development token").fill(FAKE_TOKEN);
  await page.getByRole("button", { name: "Load exam", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Offline input checks" }),
  ).toBeVisible();
}

async function approvedExam(request: APIRequestContext) {
  const id = seedExam();
  let current = await currentExam(request, id);
  let response = await request.post(
    `${API_BASE}/api/exams/${id}/regions/prepare`,
    {
      headers: { ...authHeaders, "If-Match": current.etag },
    },
  );
  expect(response.ok()).toBeTruthy();
  current = {
    document: await response.json(),
    etag: response.headers()["etag"],
  };
  const box = (label: string) => ({ x: 1, y: 1, width: 20, height: 20, label });
  response = await request.put(`${API_BASE}/api/exams/${id}/regions`, {
    headers: { ...authHeaders, "If-Match": current.etag },
    data: {
      snapshot_sha256: current.document.snapshot_sha256,
      annotations: {
        "0": [box("ID"), box("NAME"), box("CLASS")],
        "1": [box(current.document.regions.question_labels[0])],
      },
      reviewed_pages: [0, 1],
    },
  });
  expect(response.ok()).toBeTruthy();
  current = {
    document: await response.json(),
    etag: response.headers()["etag"],
  };
  response = await request.post(
    `${API_BASE}/api/exams/${id}/regions/approvals`,
    {
      headers: { ...authHeaders, "If-Match": current.etag },
      data: {
        snapshot_sha256: current.document.snapshot_sha256,
        regions_sha256: current.document.regions.review_sha256,
        confirmed: true,
      },
    },
  );
  expect(response.ok()).toBeTruthy();
  return id;
}

test("offline check needs explicit consent and cancellation never changes approvals", async ({
  page,
  request,
}) => {
  const id = await approvedExam(request);
  const before = await currentExam(request, id);
  let posts = 0;
  page.on("request", (event) => {
    if (event.method() === "POST" && event.url().includes("/jobs")) posts++;
  });
  await openChecks(page, id);
  const panel = page.getByRole("region", { name: "Offline input checks" });
  const submit = panel.getByRole("button", {
    name: "Request offline check",
    exact: true,
  });
  await expect(submit).toBeDisabled();
  await panel.getByRole("button", { name: "Refresh offline checks" }).click();
  await expect(
    panel.getByText("No offline checks requested for this exam."),
  ).toBeVisible();
  expect(posts).toBe(0);
  await panel
    .getByLabel("I request an offline check of the saved, approved inputs")
    .check();
  await submit.click();
  await expect(
    panel.getByRole("cell", { name: "Requested - not started", exact: true }),
  ).toBeVisible();
  await expect(submit).toBeDisabled();
  expect(posts).toBe(1);
  await panel.getByRole("button", { name: /^Inspect check / }).click();
  await expect(
    panel.getByText("No committed validation result."),
  ).toBeVisible();
  page.once("dialog", (dialog) => void dialog.dismiss());
  await panel
    .getByRole("button", { name: "Cancel offline check", exact: true })
    .click();
  expect(posts).toBe(1);
  page.once("dialog", (dialog) => void dialog.accept());
  await panel
    .getByRole("button", { name: "Cancel offline check", exact: true })
    .click();
  await expect(
    panel.getByRole("cell", { name: "Cancelled", exact: true }),
  ).toBeVisible();
  expect(posts).toBe(2);
  expect((await currentExam(request, id)).document).toEqual(before.document);
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await expect(panel).toHaveCount(0);
  await expect(page.getByLabel("Synthetic development token")).toHaveValue("");
});

test("lost offline request response retries the same protected job identity", async ({
  page,
  request,
}) => {
  const id = await approvedExam(request);
  await openChecks(page, id);
  const panel = page.getByRole("region", { name: "Offline input checks" });
  const bodies: unknown[] = [];
  page.on("request", (event) => {
    if (event.method() === "POST" && event.url().endsWith(`/exams/${id}/jobs`))
      bodies.push(event.postDataJSON());
  });
  await page.route(`**/api/exams/${id}/jobs`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    await route.abort("failed");
  });
  await panel
    .getByLabel("I request an offline check of the saved, approved inputs")
    .check();
  await panel
    .getByRole("button", { name: "Request offline check", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.unroute(`**/api/exams/${id}/jobs`);
  await panel.getByRole("button", { name: "Refresh offline checks" }).click();
  await expect(
    panel.getByRole("cell", { name: "Requested - not started", exact: true }),
  ).toBeVisible();
  await panel
    .getByRole("button", { name: "Retry same offline request" })
    .click();
  await expect(
    panel.getByRole("button", { name: "Request offline check", exact: true }),
  ).toBeDisabled();
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toEqual(bodies[0]);
  const response = await request.get(`${API_BASE}/api/exams/${id}/jobs`, {
    headers: authHeaders,
  });
  expect((await response.json()).items).toHaveLength(1);
});

test("offline refresh preserves unsaved boxes and stale cancellation requires explicit reload", async ({
  page,
  request,
}) => {
  const id = await approvedExam(request);
  await openChecks(page, id);
  const panel = page.getByRole("region", { name: "Offline input checks" });
  await panel
    .getByLabel("I request an offline check of the saved, approved inputs")
    .check();
  await panel
    .getByRole("button", { name: "Request offline check", exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: /^Inspect check / }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Select ID box 1", exact: true })
    .click();
  await page.getByLabel("Box x", { exact: true }).fill("8");
  const current = await currentExam(request, id);
  const changed = await request.put(`${API_BASE}/api/exams/${id}/settings`, {
    headers: { ...authHeaders, "If-Match": current.etag },
    data: current.document.settings,
  });
  expect(changed.ok()).toBeTruthy();
  const changedDocument = await changed.json();
  await panel.getByRole("button", { name: "Refresh offline checks" }).click();
  await expect(
    panel.getByRole("cell", {
      name: "Inputs changed - old check cannot run",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByLabel("Box x", { exact: true })).toHaveValue("8");
  await panel.getByRole("button", { name: /^Inspect check / }).click();
  await expect(
    panel.getByRole("button", { name: "Cancel offline check", exact: true }),
  ).toBeDisabled();
  page.once("dialog", (dialog) => void dialog.dismiss());
  await panel
    .getByRole("button", { name: "Reload current exam for checks" })
    .click();
  await expect(page.getByLabel("Box x", { exact: true })).toHaveValue("8");
  page.once("dialog", (dialog) => void dialog.accept());
  await panel
    .getByRole("button", { name: "Reload current exam for checks" })
    .click();
  await expect(
    page.getByRole("application", { name: "Page region canvas" }),
  ).toHaveCount(0);
  await panel.getByRole("button", { name: "Refresh offline checks" }).click();
  await panel.getByRole("button", { name: /^Inspect check / }).click();
  page.once("dialog", (dialog) => void dialog.accept());
  await panel
    .getByRole("button", { name: "Cancel offline check", exact: true })
    .click();
  await expect(
    panel.getByRole("cell", { name: "Cancelled", exact: true }),
  ).toBeVisible();
  expect((await currentExam(request, id)).document).toEqual(changedDocument);
});

test("offline paging and actual historical validation stay observational", async ({
  page,
  request,
}) => {
  const id = await approvedExam(request);
  const current = await currentExam(request, id);
  const prepared = await request.post(
    `${API_BASE}/api/exams/${id}/offline-inputs`,
    {
      headers: { ...authHeaders, "If-Match": current.etag },
      data: { confirmed: true },
    },
  );
  expect(prepared.ok()).toBeTruthy();
  const checkpoint = (await prepared.json()).checkpoint_id;
  const jobs: string[] = [];
  for (let index = 0; index < 21; index++) {
    const admitted = await request.post(`${API_BASE}/api/exams/${id}/jobs`, {
      headers: { ...authHeaders, "If-Match": current.etag },
      data: {
        checkpoint_id: checkpoint,
        request_id: crypto.randomUUID(),
        confirmed: true,
      },
    });
    expect(admitted.status()).toBe(201);
    jobs.push((await admitted.json()).intent.id);
  }
  execFileSync(
    "uv",
    [
      "run",
      "--frozen",
      "--extra",
      "dev",
      "--extra",
      "engine",
      "python",
      "-c",
      `
import socket
import sys
from uuid import uuid4
from pathlib import Path
from handwriting_grader.azure_ai import AzureClient
from handwriting_grader import attendance, grading, regions, rubric
from handwriting_grader_cloud.api import create_app
from handwriting_grader_cloud.auth import DevelopmentAuthenticator, Principal
from handwriting_grader_cloud.repository import SQLiteRepository
from handwriting_grader_cloud.service import ExamService
def forbidden(*args, **kwargs):
    raise AssertionError("Synthetic browser validation must not call AI, network, grading or approval actions")
AzureClient.__init__ = forbidden
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
for module, name in ((attendance, "approve_attendance"), (grading, "grade_exam"), (regions, "approve_regions"), (rubric, "approve_rubric")):
    setattr(module, name, forbidden)
service = ExamService(SQLiteRepository(Path(".local/test-results/canvas.sqlite3")))
app = create_app(service, DevelopmentAuthenticator("synthetic-offline-helper-only-not-a-real-token"))
coordinator = app.state.offline_coordinator
job = coordinator.control.jobs.get(sys.argv[1])
tenant = job["intent"]["binding"]["tenant_id"]
dispatcher = Principal(tenant, "synthetic-browser-dispatcher", frozenset({"JobDispatcher"}))
worker = Principal(tenant, "synthetic-browser-worker", frozenset({"StageWorker"}))
coordinator.dispatcher.dispatch(dispatcher, sys.argv[1], job["intent"]["message_id"], worker, uuid4())
coordinator.consume(worker, coordinator.dispatcher.queue.messages[0], uuid4())
`,
      jobs[0],
    ],
    { cwd: resolve(import.meta.dirname, "../../.."), encoding: "utf-8" },
  );
  const changed = await request.put(`${API_BASE}/api/exams/${id}/settings`, {
    headers: { ...authHeaders, "If-Match": current.etag },
    data: current.document.settings,
  });
  expect(changed.ok()).toBeTruthy();
  await openChecks(page, id);
  const panel = page.getByRole("region", { name: "Offline input checks" });
  await panel.getByRole("button", { name: "Refresh offline checks" }).click();
  await expect(panel.getByRole("row")).toHaveCount(21);
  await panel.getByRole("button", { name: "More offline checks" }).click();
  await expect(panel.getByRole("row")).toHaveCount(22);
  await expect(
    panel.getByRole("button", { name: "More offline checks" }),
  ).toHaveCount(0);
  await panel
    .getByRole("button", { name: `Inspect check ${jobs[0]}`, exact: true })
    .click();
  await expect(
    panel.getByRole("heading", { name: "Recorded offline validation" }),
  ).toBeVisible();
  await expect(
    panel.getByText(
      "Historical results describe the old saved input version only.",
      { exact: false },
    ),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Cancel offline check", exact: true }),
  ).toBeDisabled();
  await expect(panel.locator("dd").nth(0)).toHaveText(
    String(current.document.preflight.summary.students),
  );
  expect((await currentExam(request, id)).document).toEqual(
    await changed.json(),
  );
});
