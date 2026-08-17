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
