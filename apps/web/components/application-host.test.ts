import { describe, expect, it } from "vitest";
import { isPlatformControlCentreHost } from "./application-host";

describe("isPlatformControlCentreHost", () => {
  it.each([
    "admin.mykhaya.app",
    "admin.dev.mykhaya.app",
    "admin.localhost",
    "ADMIN.DEV.MYKHAYA.APP:443",
    " admin.localhost:3000 ",
  ])("accepts supported host %s", (hostname) => {
    expect(isPlatformControlCentreHost(hostname)).toBe(true);
  });

  it.each([
    "eviladmin.mykhaya.app",
    "admin.mykhaya.app.example.com",
    "",
    "admin.localhost:",
    "admin.localhost:70000",
    "admin.localhost:abc",
    "https://admin.localhost",
    "admin.localhost/path",
  ])("rejects malformed or lookalike host %s", (hostname) => {
    expect(isPlatformControlCentreHost(hostname)).toBe(false);
  });
});
