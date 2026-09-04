import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { config, middleware } from "./middleware";

describe("hostname security boundaries", () => {
	it("generates a unique nonce-bearing CSP for every application response", () => {
		const first = middleware(new NextRequest("https://admin.localhost/login", { headers: { host: "admin.localhost" } }));
		const second = middleware(new NextRequest("https://admin.localhost/login", { headers: { host: "admin.localhost" } }));
		const firstCsp = first.headers.get("content-security-policy") ?? "";
		const secondCsp = second.headers.get("content-security-policy") ?? "";
		const firstNonce = firstCsp.match(/'nonce-([^']+)'/)?.[1];
		const secondNonce = secondCsp.match(/'nonce-([^']+)'/)?.[1];

		expect(firstNonce).toBeTruthy();
		expect(secondNonce).toBeTruthy();
		expect(firstNonce).not.toBe(secondNonce);
		expect(firstCsp).toContain("script-src 'self'");
		expect(firstCsp).toContain("img-src 'self' blob: data:");
		expect(firstCsp).toContain("frame-ancestors 'none'");
		expect(firstCsp).toContain("object-src 'none'");
		expect(firstCsp).not.toContain("'unsafe-inline'");
	});

  it("rewrites the admin hostname to the internal Control Centre route", () => {
    const response = middleware(
      new NextRequest("http://admin.localhost/users", {
        headers: { host: "admin.localhost" },
      }),
    );
    expect(response.headers.get("x-middleware-rewrite")).toContain(
      "/control-centre/users",
    );
  });

  it("rewrites status to the isolated public status route", () => {
    const response = middleware(
      new NextRequest("http://status.localhost/anything", {
        headers: { host: "status.localhost" },
      }),
    );
    expect(response.headers.get("x-middleware-rewrite")).toContain(
      "/service-status",
    );
  });

  it("recognises the persistent development server hostnames", () => {
    const adminResponse = middleware(
      new NextRequest("https://admin.dev.mykhaya.app/users", {
        headers: {
          host: "admin.dev.mykhaya.app",
          "x-forwarded-proto": "https",
        },
      }),
    );
    expect(adminResponse.headers.get("x-middleware-rewrite")).toContain(
      "/control-centre/users",
    );

    const statusResponse = middleware(
      new NextRequest("https://status.dev.mykhaya.app/anything", {
        headers: {
          host: "status.dev.mykhaya.app",
          "x-forwarded-proto": "https",
        },
      }),
    );
    expect(statusResponse.headers.get("x-middleware-rewrite")).toContain(
      "/service-status",
    );
  });

  it("uses canonical PCC matching for case-insensitive host headers with ports", () => {
    const response = middleware(
      new NextRequest("http://admin.localhost:3000/users", {
        headers: { host: "ADMIN.LOCALHOST:3000" },
      }),
    );
    expect(response.headers.get("x-middleware-rewrite")).toContain(
      "/control-centre/users",
    );
  });

  it("rewrites every bare Notifications module path to its internal Control Centre route", () => {
    // Regression guard: the Notifications module's own links briefly hard-coded
    // "/control-centre"-prefixed hrefs, which this rewrite then doubled to
    // "/control-centre/control-centre/..." on the real admin host — a raw
    // Next.js 404 that unit/component tests (which never exercise middleware)
    // couldn't catch. This proves the *rewrite* side of the contract: a bare
    // browser path always lands on the intended internal route.
    const bareToInternal: Record<string, string> = {
      "/notifications": "/control-centre/notifications",
      "/notifications/templates": "/control-centre/notifications/templates",
      "/notifications/channels": "/control-centre/notifications/channels",
      "/notifications/briefing": "/control-centre/notifications/briefing",
      "/notifications/test-centre": "/control-centre/notifications/test-centre",
      "/notifications/delivery-logs": "/control-centre/notifications/delivery-logs",
    };
    for (const [bare, internal] of Object.entries(bareToInternal)) {
      const response = middleware(
        new NextRequest(`http://admin.localhost${bare}`, { headers: { host: "admin.localhost" } }),
      );
      expect(response.headers.get("x-middleware-rewrite")).toContain(internal);
    }
  });

  it("would double-prefix a request that already includes /control-centre — hrefs must stay bare", () => {
    // Documents *why* every Link/redirect target in this app must be a bare
    // path: the rewrite is unconditional and doesn't know the path might
    // already carry the prefix. A page/component that hard-codes a
    // "/control-centre"-prefixed href produces exactly this broken URL when
    // clicked on the real admin host.
    const response = middleware(
      new NextRequest("http://admin.localhost/control-centre/notifications/templates", {
        headers: { host: "admin.localhost" },
      }),
    );
    expect(response.headers.get("x-middleware-rewrite")).toContain(
      "/control-centre/control-centre/notifications/templates",
    );
  });

  it("denies internal management and status routes on the main application host", () => {
    expect(
      middleware(
        new NextRequest("http://mykhaya.app/control-centre", {
          headers: { host: "mykhaya.app" },
        }),
      ).status,
    ).toBe(404);
    expect(
      middleware(
        new NextRequest("http://mykhaya.app/service-status", {
          headers: { host: "mykhaya.app" },
        }),
      ).status,
    ).toBe(404);
  });

  it.each([
    "evil.dev.mykhaya.app",
    "phpmyadmin.dev.mykhaya.app",
    "mykhaya.app.attacker.example",
    "admin.mykhaya.app.attacker.example",
    "localhost:0",
    "localhost:70000",
  ])("rejects unknown browser host %s with 421", (host) => {
    const response = middleware(
      new NextRequest("http://localhost/", { headers: { host } }),
    );
    expect(response.status).toBe(421);
  });

  it("accepts a valid production consumer host with a port", () => {
    const response = middleware(
      new NextRequest("https://mykhaya.app:443/", {
        headers: { host: "MYKHAYA.APP:443" },
      }),
    );
    expect(response.status).toBe(200);
  });
});

describe("middleware matcher", () => {
  const [matcher] = config.matcher;
  if (!matcher) throw new Error("middleware config.matcher is unexpectedly empty");
  const matcherRegExp = new RegExp(matcher.source);

  it("excludes the transactional email logo so it's served as a plain static file", () => {
    // A request that runs through this middleware for that path gets a
    // Content-Security-Policy response header set on it — harmless to a
    // browser, but pointless overhead on a plain image fetch, and one more
    // thing that could go wrong between an external mail client's image
    // fetch and Next.js's own static-file serving for public/. Excluded the
    // same way favicon.ico already is.
    expect(matcherRegExp.test("/mykhaya-email-logo.png")).toBe(false);
  });

  it("still applies to ordinary application routes", () => {
    expect(matcherRegExp.test("/control-centre/users")).toBe(true);
    expect(matcherRegExp.test("/")).toBe(true);
  });
});
