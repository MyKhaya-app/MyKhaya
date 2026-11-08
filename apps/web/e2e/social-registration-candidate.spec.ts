import { expect, test, type Page } from "@playwright/test";

test.describe.configure({ mode: "serial", retries: 0 });

async function readMailpitMessageIds(page: Page): Promise<Set<string>> {
  const mailpitPort = process.env.MYKHAYA_E2E_MAILPIT_PORT ?? "18082";
  const response = await page.request.get(`http://127.0.0.1:${mailpitPort}/api/v1/messages`);
  if (!response.ok()) return new Set();
  const payload = await response.json() as { messages?: Array<{ ID?: string }> };
  return new Set((payload.messages ?? []).flatMap((message) => message.ID ? [message.ID] : []));
}

async function readLatestMfaCode(page: Page, ignoredMessageIds = new Set<string>()): Promise<string> {
  const mailpitPort = process.env.MYKHAYA_E2E_MAILPIT_PORT ?? "18082";
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const messagesResponse = await page.request.get(`http://127.0.0.1:${mailpitPort}/api/v1/messages`);
      if (messagesResponse.ok()) {
        const payload = await messagesResponse.json() as { messages?: Array<{ ID?: string; Created?: string }> };
        const messages = [...(payload.messages ?? [])].sort((left, right) =>
          String(right.Created ?? "").localeCompare(String(left.Created ?? "")),
        );
        for (const message of messages) {
          if (!message.ID || ignoredMessageIds.has(message.ID)) continue;
          const detailResponse = await page.request.get(`http://127.0.0.1:${mailpitPort}/api/v1/message/${message.ID}`);
          if (!detailResponse.ok()) continue;
          const detail = await detailResponse.json() as { Text?: string; HTML?: string };
          const messageBody = `${detail.Text ?? ""}\n${detail.HTML ?? ""}`;
          const match = messageBody.match(/\b\d{6}\b/);
          if (match) return match[0];
        }
      }
    } catch {
      // Mailpit may take a moment to become reachable through the host port.
    }
    await page.waitForTimeout(500);
  }
  throw new Error("Synthetic MFA email code was not delivered to Mailpit.");
}

async function completeBrowserMfa(page: Page, screenshot: string, ignoredMessageIds?: Set<string>): Promise<void> {
  await expect(page.getByRole("heading", { name: /One more security check|Verify it's you/ })).toBeVisible();
  await page.screenshot({ path: screenshot, fullPage: true });
  await expect(page.getByLabel("Verification code")).toBeVisible();
  const code = await readLatestMfaCode(page, ignoredMessageIds);
  await page.getByLabel("Verification code").fill(code);
  await page.getByRole("button", { name: "Verify" }).click();
}

async function latestMailpitBody(page: Page, pattern: RegExp, ignoredMessageIds = new Set<string>()): Promise<string> {
  const mailpitPort = process.env.MYKHAYA_E2E_MAILPIT_PORT ?? "18082";
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const response = await page.request.get(`http://127.0.0.1:${mailpitPort}/api/v1/messages`);
    if (response.ok()) {
      const payload = await response.json() as { messages?: Array<{ ID?: string; Created?: string }> };
      const messages = [...(payload.messages ?? [])].sort((left, right) =>
        String(right.Created ?? "").localeCompare(String(left.Created ?? "")),
      );
      for (const message of messages) {
        if (!message.ID || ignoredMessageIds.has(message.ID)) continue;
        const detailResponse = await page.request.get(`http://127.0.0.1:${mailpitPort}/api/v1/message/${message.ID}`);
        if (!detailResponse.ok()) continue;
        const detail = await detailResponse.json() as { Text?: string; HTML?: string };
        const body = `${detail.Text ?? ""}\n${detail.HTML ?? ""}`;
        if (pattern.test(body)) return body;
      }
    }
    await page.waitForTimeout(500);
  }
  throw new Error("Expected synthetic Mailpit message was not delivered.");
}

async function completeNewHome(page: Page, homeName: string, beta = false): Promise<void> {
  if (beta) {
    await expect(page.getByRole("heading", { name: /Welcome to the MyKhaya Founding Beta/i })).toBeVisible();
    const betaTerms = page.getByRole("checkbox");
    if (await betaTerms.count()) await betaTerms.check();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "Create your Home" })).toBeVisible();
    await page.getByLabel("Home name").fill(homeName);
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "Confirm your Beta enrolment" })).toBeVisible();
    await page.getByRole("button", { name: "Join the Founding Beta" }).click();
  } else {
    await expect(page.getByRole("heading", { name: "How would you like to use MyKhaya?" })).toBeVisible();
    await page.getByRole("button", { name: "Create a new Home" }).click();
    await page.getByLabel("Home name").fill(homeName);
    await page.getByRole("button", { name: "Create our Home" }).click();
    await expect(page.getByRole("heading", { name: "Choose your MyKhaya plan" })).toBeVisible();
    await page.getByRole("button", { name: "Continue with Free" }).click();
  }
  await page.waitForURL(/\/home$/);
}

async function completePasswordMfaIfShown(page: Page, name: string): Promise<void> {
  if (page.url().includes("/mfa?transaction=")) {
    const previous = await readMailpitMessageIds(page);
    await completeBrowserMfa(page, `test-results/${name}-mfa.png`, previous);
  }
}

test("synthetic Google registration completes the browser security handoff", async ({ page }) => {
  page.on("console", (message) => console.log(`[browser:${message.type()}] ${message.text()}`));
  page.on("requestfailed", (request) => console.log(`[request-failed] ${request.method()} ${request.url()} ${request.failure()?.errorText ?? "unknown"}`));
  page.on("response", async (response) => {
    if (response.url().includes("/api/v1/")) {
      console.log(`[api-response] ${response.status()} ${response.headers()["content-type"] ?? ""} ${response.url()}`);
    }
    if (response.url().includes("/api/v1/auth/providers")) {
      console.log(`[providers-body] ${(await response.text()).slice(0, 1000)}`);
    }
  });
  await page.goto("/register");
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await page.screenshot({ path: "test-results/google-register-start.png", fullPage: true });

  const startRequest = page.waitForRequest((request) =>
    request.url().includes("/api/v1/auth/google/start?") && request.method() === "GET",
  );
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await startRequest;
  await page.waitForURL(/\/login\?google=choose&transaction=/);
  await expect(page.getByRole("heading", { name: "Continue with Google" })).toBeVisible();
  await page.screenshot({ path: "test-results/google-register-choice.png", fullPage: true });

  await page.getByRole("button", { name: "Create a new account" }).click();
  const legal = page.locator(".auth-legal-consent input[type=checkbox]");
  await expect(legal).toHaveCount(1);
  await legal.check();
  await page.getByRole("button", { name: "Accept and create account" }).click();
  await page.waitForURL(/\/onboarding$|\/mfa\?transaction=/);
  if (page.url().includes("/mfa?transaction=")) {
    await completeBrowserMfa(page, "test-results/google-register-mfa.png");
    await page.waitForURL(/\/onboarding$/);
  }
  await expect(page.getByRole("heading", { name: "How would you like to use MyKhaya?" })).toBeVisible();
  await page.getByRole("button", { name: "Create a new Home" }).click();
  await page.getByLabel("Home name").fill("Google E2E Home");
  await page.getByRole("button", { name: "Create our Home" }).click();
  await expect(page.getByRole("heading", { name: "Choose your MyKhaya plan" })).toBeVisible();
  await page.getByRole("button", { name: "Continue with Free" }).click();
  await page.waitForURL(/\/home$/);
  await page.screenshot({ path: "test-results/google-register-home.png", fullPage: true });

  const csrf = await page.evaluate(() => document.cookie.match(/(?:^|; )mk_csrf=([^;]+)/)?.[1] ?? "");
  const logoutResponse = await page.request.post("/api/v1/auth/logout", {
    headers: { "X-CSRF-Token": decodeURIComponent(csrf) },
  });
  expect(logoutResponse.status()).toBe(204);
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await page.waitForURL(/\/mfa\?transaction=/);
  const previousMessages = await readMailpitMessageIds(page);
  await completeBrowserMfa(page, "test-results/google-returning-mfa.png", previousMessages);
  await page.waitForURL(/\/home$/);
  await expect(page.getByRole("heading", { name: "Google" })).toBeVisible();
  await page.screenshot({ path: "test-results/google-returning-home.png", fullPage: true });
});

test("synthetic Apple registration completes the browser security handoff", async ({ page }) => {
  await page.goto("/register");
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await page.screenshot({ path: "test-results/apple-register-start.png", fullPage: true });
  await page.getByRole("button", { name: "Continue with Apple" }).click();
  await page.waitForURL(/\/login\?apple=choose&transaction=/);
  await expect(page.getByRole("heading", { name: "Continue with Apple" })).toBeVisible();
  await page.getByRole("button", { name: "Create a new account" }).click();
  await page.locator(".auth-legal-consent input[type=checkbox]").all().then(async (boxes) => {
    for (const box of boxes) await box.check();
  });
  await page.getByRole("button", { name: "Accept and create account" }).click();
  await page.waitForURL(/\/onboarding$|\/mfa\?transaction=/);
  await completePasswordMfaIfShown(page, "apple-register");
  await completeNewHome(page, "Apple E2E Home");
  await page.screenshot({ path: "test-results/apple-register-home.png", fullPage: true });

  const csrf = await page.evaluate(() => document.cookie.match(/(?:^|; )mk_csrf=([^;]+)/)?.[1] ?? "");
  expect((await page.request.post("/api/v1/auth/logout", { headers: { "X-CSRF-Token": decodeURIComponent(csrf) } })).status()).toBe(204);
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue with Apple" }).click();
  await page.waitForURL(/\/mfa\?transaction=/);
  await completePasswordMfaIfShown(page, "apple-returning");
  await page.waitForURL(/\/home$/);
  await expect(page.getByRole("heading", { name: "Apple" })).toBeVisible();
  await page.screenshot({ path: "test-results/apple-returning-home.png", fullPage: true });
});

test("synthetic email registration completes verification and returning login", async ({ page }) => {
  const email = "email.synthetic@e2e.mykhaya.dev";
  const password = "Synthetic-E2E-password-123!";
  await page.goto("/register");
  await page.getByLabel("Your name").fill("Synthetic Email User");
  await page.locator("#register-email").fill(email);
  await page.locator("#register-password").fill(password);
  await page.locator("#register-confirm").fill(password);
  for (const box of await page.locator(".register-form input[type=checkbox]").all()) await box.check();
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL(/\/verify-email$/);
  const verificationBody = await latestMailpitBody(page, /\/verify-email\?token=/);
  const verificationUrl = verificationBody.match(/https?:\/\/[^\s<]+\/verify-email\?token=[^\s<]+/)?.[0];
  expect(verificationUrl).toBeTruthy();
  await page.goto(verificationUrl!.replace(/&amp;/g, "&"));
  await expect(page.getByText(/Your email is verified/i)).toBeVisible();
  await page.getByRole("link", { name: "Continue to sign in" }).click();
  await page.locator("#signin-email").fill(email);
  await page.locator("#signin-password").fill(password);
  const firstMfaMessages = await readMailpitMessageIds(page);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/home$|\/mfa\?transaction=/);
  if (page.url().includes("/mfa?transaction=")) {
    await completeBrowserMfa(page, "test-results/email-register-mfa.png", firstMfaMessages);
  }
  await completeNewHome(page, "Email E2E Home");
  const csrf = await page.evaluate(() => document.cookie.match(/(?:^|; )mk_csrf=([^;]+)/)?.[1] ?? "");
  expect((await page.request.post("/api/v1/auth/logout", { headers: { "X-CSRF-Token": decodeURIComponent(csrf) } })).status()).toBe(204);
  await page.goto("/login");
  await page.locator("#signin-email").fill(email);
  await page.locator("#signin-password").fill(password);
  const returningMfaMessages = await readMailpitMessageIds(page);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/home$|\/mfa\?transaction=/);
  if (page.url().includes("/mfa?transaction=")) {
    await completeBrowserMfa(page, "test-results/email-returning-mfa.png", returningMfaMessages);
  }
  await page.waitForURL(/\/home$/);
});

async function completeBetaSocial(page: Page, provider: "Apple" | "Google", invitation: string, homeName: string): Promise<void> {
  await page.goto(`/register?beta=1&beta_invitation=${encodeURIComponent(invitation)}`);
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await page.getByRole("button", { name: `Join Beta with ${provider}` }).click();
  await page.waitForURL(new RegExp(`\\/login\\?${provider.toLowerCase()}=choose&transaction=`));
  await page.getByRole("button", { name: "Create a new account" }).click();
  for (const box of await page.locator(".auth-legal-consent input[type=checkbox]").all()) await box.check();
  await page.getByRole("button", { name: "Accept and create account" }).click();
  await page.waitForURL(/\/onboarding(?:\?beta=1[^/]*)?$|\/mfa\?transaction=/);
  await completePasswordMfaIfShown(page, `${provider.toLowerCase()}-beta-register`);
  await completeNewHome(page, homeName, true);
  await page.screenshot({ path: `test-results/${provider.toLowerCase()}-beta-home.png`, fullPage: true });

  const csrf = await page.evaluate(() => document.cookie.match(/(?:^|; )mk_csrf=([^;]+)/)?.[1] ?? "");
  expect((await page.request.post("/api/v1/auth/logout", { headers: { "X-CSRF-Token": decodeURIComponent(csrf) } })).status()).toBe(204);
  await page.goto(`/login?beta=1&beta_invitation=${encodeURIComponent(invitation)}`);
  await page.getByRole("button", { name: `Continue with ${provider}` }).click();
  await page.waitForURL(/\/mfa\?transaction=/);
  await completePasswordMfaIfShown(page, `${provider.toLowerCase()}-beta-returning`);
  await page.waitForURL(/\/home$/);
}

test("synthetic Beta Google registration preserves invitation and entitlement", async ({ page }) => {
  await completeBetaSocial(page, "Google", "e2e-beta-google-invitation-token-0001", "Beta Google E2E Home");
});

test("synthetic Beta Apple registration preserves invitation and entitlement", async ({ page }) => {
  await completeBetaSocial(page, "Apple", "e2e-beta-apple-invitation-token-0001", "Beta Apple E2E Home");
});

test("synthetic Beta email registration verifies and enrols", async ({ page }) => {
  const email = "beta.email@e2e.mykhaya.dev";
  const password = "Synthetic-E2E-beta-password-123!";
  const invitation = "e2e-beta-email-invitation-token-0001";
  await page.goto(`/register?beta=1&beta_invitation=${encodeURIComponent(invitation)}`);
  await page.getByLabel("Your name").fill("Synthetic Beta Email User");
  await page.locator("#register-email").fill(email);
  await page.locator("#register-password").fill(password);
  await page.locator("#register-confirm").fill(password);
  for (const box of await page.locator(".register-form input[type=checkbox]").all()) await box.check();
  const betaVerificationMessages = await readMailpitMessageIds(page);
  await page.getByRole("button", { name: "Create account and continue" }).click();
  await page.waitForURL(/\/verify-email\?beta=1/);
  const body = await latestMailpitBody(page, /\/verify-email\?token=/, betaVerificationMessages);
  const link = body.match(/https?:\/\/[^\s<]+\/verify-email\?token=[^\s<]+/)?.[0];
  expect(link).toBeTruthy();
  await page.goto(link!.replace(/&amp;/g, "&"));
  await expect(page.getByText(/Your email is verified/i)).toBeVisible();
  await page.getByRole("link", { name: "Continue to sign in" }).click();
  await page.locator("#signin-email").fill(email);
  await page.locator("#signin-password").fill(password);
  const betaMfaMessages = await readMailpitMessageIds(page);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/onboarding(?:\?beta=1[^/]*)?$|\/mfa\?transaction=/);
  if (page.url().includes("/mfa?transaction=")) {
    await completeBrowserMfa(page, "test-results/email-beta-register-mfa.png", betaMfaMessages);
  }
  await completeNewHome(page, "Email Beta E2E Home", true);
  await page.waitForURL(/\/home$/);
});
