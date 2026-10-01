import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

// A tiny but valid-looking JPEG; the mock extractor never reads the bytes.
const JPEG = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.alloc(2048)]);

test("sign up → upload → edit → dashboard → export", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;
  // The 15th of the current month (UTC, as the API counts months), so it lands in "this month".
  const thisMonth = new Date().toISOString().slice(0, 7);
  const purchaseDate = `${thisMonth}-15`;

  // 1. Sign up
  await page.goto("/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Confirm password").fill("e2e-password-123");
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText("No spending recorded this month yet.")).toBeVisible();

  // 2. Upload (mock extraction)
  await page.getByRole("link", { name: "Upload", exact: true }).click();
  await page.getByLabel("Choose receipt files").setInputFiles({
    name: "receipt.jpg",
    mimeType: "image/jpeg",
    buffer: JPEG,
  });
  await page.getByRole("link", { name: "View receipt" }).click();

  // Processing → ready without a manual refresh.
  await expect(page.getByText("Ready", { exact: true })).toBeVisible();
  const merchant = page.getByLabel("Merchant", { exact: true });
  await expect(merchant).not.toHaveValue("");

  // 3. Edit
  await merchant.fill("E2E Coffee Roasters");
  await page.getByLabel("Date", { exact: true }).fill(purchaseDate);
  await page.getByLabel("Total", { exact: true }).fill("42.42");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Changes saved")).toBeVisible();

  // Edits persist across a reload.
  await page.reload();
  await expect(page.getByLabel("Merchant", { exact: true })).toHaveValue("E2E Coffee Roasters");
  await expect(page.getByLabel("Total", { exact: true })).toHaveValue("42.42");

  // 4. Dashboard reflects it
  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(page.getByText("$42.42").first()).toBeVisible();
  const byCategory = page.getByRole("region", { name: /Spending by category/ });
  const row = byCategory.getByRole("row").filter({ hasText: "$42.42" });
  await expect(row).toContainText("100%");

  // 5. Export
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: /^Export .* CSV$/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^receipts-\d{4}-\d{2}-\d{2}\.csv$/);
  const csv = (await readFile((await download.path())!)).toString("utf-8");
  const lines = csv.replace(/^﻿/, "").trim().split("\r\n");
  expect(lines[0]).toBe("date,merchant,category,subtotal,tax,tip,total,tags,notes");
  expect(lines).toHaveLength(2);
  expect(lines[1]).toContain(`${purchaseDate},E2E Coffee Roasters,`);
  expect(lines[1]).toContain(",42.42,");
});
