import { type Page, expect, test } from "@playwright/test";

const PASSWORD = process.env.AEGIS_DEMO_PASSWORD || "Aegis-Demo-Only-2026";
const SHOTS = process.env.AEGIS_SCREENSHOT_DIR;

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

const FIELD_NOTES =
  "Field notes, 14 March. The river was higher than last week, brown and quick under the footbridge. We counted eleven herons on the gravel bar before the rain started, then gave up and sheltered under the alders. Ravi thinks the new culvert upstream is changing how silt settles near the bend; I am not convinced yet, because the same pattern showed up in 2019 before any construction. Next visit we should bring the turbidity meter and take readings at both ends of the bar.";

test("investigator → analysis → reviewer decision → report → audit", async ({ browser }) => {
  const ref = `E2E-${Date.now()}`;
  const inv = await browser.newPage();
  await signIn(inv, "investigator@aegis.demo");
  await shot(inv, "01-overview");

  await inv.getByRole("link", { name: "New Investigation", exact: true }).click();
  await inv.getByLabel("Case title").fill("End-to-end authorship triage");
  await inv.getByLabel("Case reference").fill(ref);
  await inv.getByLabel("Purpose").fill("Automated end-to-end test of the AEGIS investigation workflow.");
  await inv.getByLabel("Assigned independent reviewer").selectOption({ label: "Demo Independent Reviewer" });
  await shot(inv, "02-new-investigation");
  await inv.getByRole("button", { name: "Create case and continue" }).click();

  await inv.locator('input[type="file"]').setInputFiles({ name: "field-notes.txt", mimeType: "text/plain", buffer: Buffer.from(FIELD_NOTES) });
  await expect(inv.getByText("local SHA-256")).toBeVisible();
  await inv.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(inv.getByText("matches local hash")).toBeVisible();
  await shot(inv, "03-evidence-acquired");
  await inv.getByRole("button", { name: "Continue" }).click();
  await expect(inv.getByText("Text authenticity triage").first()).toBeVisible();
  await shot(inv, "04-profile");
  await inv.getByRole("button", { name: "Queue analyses" }).click();

  await expect(inv.getByText(ref)).toBeVisible();
  await inv.getByRole("tab", { name: /Analyses/ }).click();
  await expect(inv.getByText("Automated evidence assessment")).toBeVisible({ timeout: 90_000 });
  await expect(inv.getByText("Inconclusive").first()).toBeVisible();
  await expect(inv.getByText("Unavailable").first()).toBeVisible();
  await shot(inv, "05-analysis");

  await inv.getByRole("tab", { name: /Review/ }).click();
  await inv.getByPlaceholder("Add an annotation…").fill("Only descriptive statistics and the reference watermark verifier ran.");
  await inv.getByRole("button", { name: "Add annotation" }).click();
  await expect(inv.getByText("Only descriptive statistics and the reference watermark verifier ran.")).toBeVisible();
  await inv.getByRole("button", { name: "Request human review" }).click();
  await expect(inv.getByText("Human review").first()).toBeVisible();

  const rev = await browser.newPage();
  await signIn(rev, "reviewer@aegis.demo");
  await rev.goto(inv.url());
  await rev.getByRole("tab", { name: /Review/ }).click();
  await rev.getByLabel("Rationale").fill("No interpretable detector output; descriptive statistics only. The watermark verifier found no reference watermark, which says nothing about authorship.");
  await rev.getByRole("button", { name: "Record authenticated decision" }).click();
  await expect(rev.getByText("decision hash")).toBeVisible();
  await shot(rev, "06-review");

  await inv.reload();
  await inv.getByRole("tab", { name: /Reports/ }).click();
  await inv.getByRole("button", { name: "Generate draft report" }).click();
  await expect(inv.getByText("v1")).toBeVisible();
  await inv.getByRole("button", { name: "Verify" }).click();
  await expect(inv.getByText("intact & reproducible")).toBeVisible();
  await shot(inv, "07-reports");

  await rev.reload();
  await rev.getByRole("tab", { name: /Reports/ }).click();
  await rev.getByRole("button", { name: "Finalise" }).click();
  await expect(rev.getByText("final", { exact: true })).toBeVisible();

  const aud = await browser.newPage();
  await signIn(aud, "auditor@aegis.demo");
  await aud.goto("/audit");
  await aud.getByRole("button", { name: "Verify entire chain" }).click();
  await expect(aud.getByText(/Chain valid/)).toBeVisible();
  await shot(aud, "08-audit");
});

test("permission-denied paths and capability honesty", async ({ page }) => {
  await signIn(page, "researcher@aegis.demo").catch(async () => {
    // Researchers have no case access, so the overview call is refused; the shell still loads.
  });
  await page.goto("/research");
  await expect(page.getByRole("heading", { name: /Research bench/ })).toBeVisible();
  await expect(page.getByText("Case Files")).toHaveCount(0);
  await page.goto("/");
  await expect(page.getByText("Not permitted")).toBeVisible();
});

test("tour of every primary screen", async ({ page }) => {
  await signIn(page, "admin@aegis.demo");
  for (const [path, heading, name] of [
    ["/cases", "Case files", "09-cases"],
    ["/forensics/text", "Text forensics", "10-text"],
    ["/forensics/image", "Image forensics", "11-image"],
    ["/forensics/audio", "Audio forensics", "12-audio"],
    ["/forensics/video", "Video forensics", "13-video"],
    ["/provenance", "Provenance & watermarks", "14-provenance"],
    ["/evidence", "Evidence vault", "15-vault"],
    ["/research", "Research bench", "16-research"],
    ["/benchmarks", "Benchmark laboratory", "17-benchmarks"],
    ["/reports", "Reports", "18-reports"],
    ["/audit", "Audit & compliance", "19-audit"],
    ["/admin", "Administration", "20-admin"],
    ["/health", "System health", "21-health"],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: new RegExp(heading) }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await shot(page, name);
  }
});
