import { describe, expect, it } from "vitest";
import { applicationHostKind, isPlatformControlCentreHost } from "./application-host";

describe("applicationHostKind", () => {
  it.each(["mykhaya.app", "dev.mykhaya.app", "localhost:3000", "127.0.0.1:8080"])(
    "accepts consumer host %s",
    (host) => expect(applicationHostKind(host)).toBe("consumer"),
  );
  it.each(["evil.dev.mykhaya.app", "phpmyadmin.dev.mykhaya.app", "mykhaya.app.attacker.example", "admin.mykhaya.app.attacker.example", "localhost:0", "localhost:70000", "localhost:abc", "https://localhost"])(
    "fails closed for %s",
    (host) => expect(applicationHostKind(host)).toBe("unknown"),
  );
  it("classifies PCC and status separately", () => {
    expect(applicationHostKind("ADMIN.MYKHAYA.APP:443")).toBe("admin");
    expect(applicationHostKind("status.dev.mykhaya.app:443")).toBe("status");
  });
});

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
