import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "./middleware";

describe("hostname security boundaries", () => {
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
