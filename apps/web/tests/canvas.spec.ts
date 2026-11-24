import { expect, test } from "@playwright/test";
import {
  API_BASE,
  addBox,
  authHeaders,
  currentExam,
  openExam,
  seedExam,
  FAKE_TOKEN,
  exportInputs,
} from "./support";

for (const zoom of [0.25, 0.5, 2]) {
  test(`pointer geometry is canonical at zoom ${zoom}`, async ({
    page,
    request,
  }) => {
    const id = await openExam(page);
    await page.getByRole("button", { name: "Page 2: needs review" }).click();
    await expect(
      page.getByLabel("I reviewed page 2 and its boxes"),
    ).toBeEnabled();
    await page.getByLabel("New box label").selectOption("1");
    await page
      .getByRole("combobox", { name: "Zoom", exact: true })
      .selectOption(String(zoom));
    const canvas = page.getByRole("application", {
      name: "Page region canvas",
    });
    const bounds = (await canvas.boundingBox())!;
    const { document } = await currentExam(request, id);
    const dimensions = document.regions.pages[1];
    await page.mouse.move(
      bounds.x + (40.25 * bounds.width) / dimensions.width,
      bounds.y + (50.25 * bounds.height) / dimensions.height,
    );
    await page.mouse.down();
    await page.mouse.move(
      bounds.x + (80.75 * bounds.width) / dimensions.width,
      bounds.y + (95.75 * bounds.height) / dimensions.height,
      { steps: 3 },
    );
    await page.mouse.up();
    await expect(page.getByLabel("Box x", { exact: true })).toHaveValue("40");
    await expect(page.getByLabel("Box y", { exact: true })).toHaveValue("50");
    await expect(page.getByLabel("Box width", { exact: true })).toHaveValue(
      "41",
    );
    await expect(page.getByLabel("Box height", { exact: true })).toHaveValue(
      "46",
    );
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Save draft", exact: true }),
    ).toBeDisabled();
    const saved = await currentExam(request, id);
    expect(saved.document.regions.annotations["1"][0]).toEqual({
      x: 40,
      y: 50,
      width: 41,
      height: 46,
      label: "1",
    });
  });
}

test("keyboard edits reset page review and explicit approval is required", async ({
  page,
  request,
}) => {
  let approvalRequests = 0;
  page.on("request", (event) => {
    if (event.method() === "POST" && event.url().endsWith("/regions/approvals"))
      approvalRequests++;
  });
  const id = await openExam(page);
  expect(approvalRequests).toBe(0);
  await addBox(page, "ID");
  await page.getByLabel("I reviewed page 1 and its boxes").check();
  const canvas = page.getByRole("application", { name: "Page region canvas" });
  await canvas.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Shift+ArrowDown");
  await expect(page.getByLabel("Box x", { exact: true })).toHaveValue("1");
  await expect(page.getByLabel("Box y", { exact: true })).toHaveValue("10");
  await expect(
    page.getByLabel("I reviewed page 1 and its boxes"),
  ).not.toBeChecked();
  await addBox(page, "NAME");
  await addBox(page, "CLASS");
  await page.getByLabel("I reviewed page 1 and its boxes").check();
  await page.getByRole("button", { name: "Page 2: needs review" }).click();
  await expect(
    page.getByLabel("I reviewed page 2 and its boxes"),
  ).toBeEnabled();
  await addBox(page, "1");
  await page.getByLabel("I reviewed page 2 and its boxes").check();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  const approve = page.getByRole("button", {
    name: "Approve regions",
    exact: true,
  });
  await expect(approve).toBeDisabled();
  expect(approvalRequests).toBe(0);
  await page
    .getByLabel("I approve this saved layout for scripts sharing it")
    .check();
  await approve.click();
  await expect(page.getByRole("status")).toHaveText(
    "Saved region layout approved",
  );
  expect(approvalRequests).toBe(1);
  const result = await currentExam(request, id);
  expect(result.document.state).toBe("REGIONS_REVIEWED");
  expect(result.document.approvals).toHaveLength(2);
  await page.getByRole("button", { name: "Select 1 box 1" }).click();
  await page.getByLabel("Box x", { exact: true }).fill("10");
  await expect(page.getByRole("status")).toHaveText(
    "Unsaved edits - not approved",
  );
  await expect(
    page.getByLabel("I approve this saved layout for scripts sharing it"),
  ).not.toBeChecked();
  page.once("dialog", (dialog) => void dialog.accept());
  await page
    .getByRole("button", {
      name: "Change inputs (invalidate approvals)",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("application", { name: "Page region canvas" }),
  ).toHaveCount(0);
  const reopened = await currentExam(request, id);
  expect(reopened.document.state).toBe("SETUP");
  expect(reopened.document.current_approval).toBeNull();
  expect(reopened.document.current_region_approval).toBeNull();
  expect(reopened.document.approvals).toHaveLength(2);
});

test("stale save preserves boxes and reapplication clears all reviews", async ({
  page,
  request,
}) => {
  const id = await openExam(page);
  await addBox(page, "ID");
  await page.getByLabel("I reviewed page 1 and its boxes").check();
  const { document, etag } = await currentExam(request, id);
  const changed = await request.put(`${API_BASE}/api/exams/${id}/regions`, {
    headers: { ...authHeaders, "If-Match": etag },
    data: {
      snapshot_sha256: document.snapshot_sha256,
      annotations: {
        "0": [{ x: 5, y: 5, width: 20, height: 20, label: "NAME" }],
        "1": [],
      },
      reviewed_pages: [],
    },
  });
  expect(changed.ok()).toBeTruthy();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByLabel("Box x", { exact: true })).toHaveValue("0");
  await page
    .getByRole("button", {
      name: "Reapply my boxes to latest (review again)",
      exact: true,
    })
    .click();
  await expect(
    page.getByLabel("I reviewed page 1 and its boxes"),
  ).not.toBeChecked();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save draft", exact: true }),
  ).toBeDisabled();
  expect(
    (await currentExam(request, id)).document.regions.annotations["0"][0].label,
  ).toBe("ID");
});

test("changed inputs prohibit reapplying old coordinates", async ({
  page,
  request,
}) => {
  const id = await openExam(page);
  await addBox(page, "ID");
  const { document, etag } = await currentExam(request, id);
  const changed = await request.put(`${API_BASE}/api/exams/${id}/settings`, {
    headers: { ...authHeaders, "If-Match": etag },
    data: { ...document.settings, pages_per_student: 1 },
  });
  expect(changed.ok()).toBeTruthy();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Reapply my boxes to latest (review again)",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(page.getByLabel("Box x", { exact: true })).toHaveValue("0");
  await page
    .getByRole("button", {
      name: "Reload server draft (discard mine)",
      exact: true,
    })
    .click();
  await expect(
    page.getByText("Complete input review before preparing the template."),
  ).toBeVisible();
});

test("credentials remain memory-only and a reload signs out", async ({
  page,
}) => {
  await openExam(page);
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
  expect(new URL(page.url()).search).toBe("");
  await page.reload();
  await expect(page.getByLabel("Synthetic development token")).toHaveValue("");
  await expect(page.getByRole("button", { name: "Load exam" })).toBeVisible();
});

test("owned selection loads an exam without typing its UUID and clears on disconnect", async ({
  page,
}) => {
  const id = seedExam();
  await page.goto("/");
  await page.getByLabel("Synthetic development token").fill(FAKE_TOKEN);
  const show = page.getByRole("button", { name: "Show my exams", exact: true });
  await show.click();
  await expect(show).toBeEnabled();
  const selector = page.getByRole("combobox", {
    name: "Owned exam",
    exact: true,
  });
  await expect(selector).toBeVisible();
  while ((await selector.locator(`option[value="${id}"]`).count()) === 0) {
    await page
      .getByRole("button", { name: "More owned exams", exact: true })
      .click();
    await expect(show).toBeEnabled();
  }
  await selector.selectOption(id);
  await page.getByRole("button", { name: "Load exam", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Synthetic canvas demonstration" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await expect(selector).toHaveCount(0);
  await expect(page.getByLabel("Synthetic development token")).toHaveValue("");
});

for (const attendance of [false, true]) {
  test(`create, upload and explicitly review inputs with attendance ${attendance}`, async ({
    page,
    request,
  }, testInfo) => {
    const files = exportInputs(
      testInfo.outputPath("synthetic-inputs"),
      attendance,
    );
    await page.goto("/");
    await page.getByLabel("Synthetic development token").fill(FAKE_TOKEN);
    await page
      .getByLabel("New exam title", { exact: true })
      .fill("Synthetic browser input workflow");
    const creation = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/exams",
    );
    await page
      .getByRole("button", { name: "Create new exam", exact: true })
      .click();
    const id = (await (await creation).json()).id as string;
    await expect(
      page.getByRole("heading", { name: "Input setup and review" }),
    ).toBeVisible();
    await page.getByLabel("I confirmed scan order").check();
    await page.getByLabel("All scripts use the same layout").check();
    await page
      .getByRole("button", { name: "Save input settings", exact: true })
      .click();
    for (const [kind, path] of Object.entries(files)) {
      await expect(
        page.getByLabel(`Upload ${kind}`, { exact: false }),
      ).toBeEnabled();
      await page
        .getByLabel(`Upload ${kind}`, { exact: false })
        .setInputFiles(path);
      await expect(
        page.getByText(`${kind} uploaded:`, { exact: false }),
      ).toBeVisible();
    }
    await page
      .getByRole("button", {
        name: "Validate inputs for review",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("row").filter({ hasText: "001" }),
    ).toContainText("present");
    await expect(
      page.getByRole("row").filter({ hasText: "002" }),
    ).toContainText(attendance ? "absent" : "present");
    await expect(
      page.getByRole("cell", { name: "Synthetic criterion", exact: true }),
    ).toBeVisible();
    const approve = page.getByRole("button", {
      name: "Approve input snapshot",
      exact: true,
    });
    await expect(approve).toBeDisabled();
    await page
      .getByLabel("I reviewed the roster, rubric and scan settings")
      .check();
    if (attendance) {
      await expect(approve).toBeDisabled();
      await page
        .getByLabel("I separately confirm the present/absent attendance list")
        .check();
    }
    await approve.click();
    const prepare = page.getByRole("button", {
      name: "Prepare template",
      exact: true,
    });
    await expect(prepare).toBeEnabled();
    const persisted = await currentExam(request, id);
    expect(persisted.document.state).toBe("INPUTS_REVIEWED");
    expect(persisted.document.approvals).toHaveLength(attendance ? 2 : 1);
    expect(persisted.document.preflight.rubric_review[0].marking_scheme).toBe(
      "Synthetic criterion",
    );
    await prepare.click();
    await expect(
      page.getByLabel("I reviewed page 1 and its boxes"),
    ).toBeEnabled();
  });
}
