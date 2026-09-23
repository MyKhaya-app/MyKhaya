import { describe, expect, it } from "vitest";
import {
  connectivityLabel,
  hubStatusMessage,
  notificationPermissionLabel,
  platformLabel,
} from "./help-support-logic";

describe("hubStatusMessage", () => {
  it("shows the plain-language operational message, not the backend's raw wording", () => {
    expect(hubStatusMessage("operational", "Operational")).toBe("All systems operational");
  });

  it("collapses degraded performance to the 'some services' wording", () => {
    expect(hubStatusMessage("degraded_performance", "Some systems are experiencing degraded performance")).toBe(
      "Some services are experiencing problems",
    );
  });

  it("collapses partial outage to the same 'some services' wording", () => {
    expect(hubStatusMessage("partial_outage", "Partial service disruption")).toBe(
      "Some services are experiencing problems",
    );
  });

  it("shows 'Service disruption' for a major outage", () => {
    expect(hubStatusMessage("major_outage", "Major service disruption")).toBe("Service disruption");
  });

  it("passes through the backend's own maintenance wording rather than framing it as a problem", () => {
    expect(hubStatusMessage("maintenance", "Scheduled maintenance in progress")).toBe(
      "Scheduled maintenance in progress",
    );
  });
});

describe("platformLabel", () => {
  it("labels each real platform value truthfully", () => {
    expect(platformLabel("ios")).toBe("iOS app");
    expect(platformLabel("android")).toBe("Android app");
    expect(platformLabel("web")).toBe("Web browser");
  });
});

describe("notificationPermissionLabel", () => {
  it("labels every known permission status", () => {
    expect(notificationPermissionLabel("granted")).toBe("Enabled");
    expect(notificationPermissionLabel("denied")).toBe("Off");
    expect(notificationPermissionLabel("not_requested")).toBe("Not requested");
    expect(notificationPermissionLabel("restricted")).toBe("Restricted");
    expect(notificationPermissionLabel("unsupported")).toBe("Unsupported");
  });

  it("never fabricates a specific status for something unrecognised", () => {
    expect(notificationPermissionLabel("something-new")).toBe("Unknown");
  });
});

describe("connectivityLabel", () => {
  it("reflects true/false truthfully", () => {
    expect(connectivityLabel(true)).toBe("Online");
    expect(connectivityLabel(false)).toBe("Offline");
  });

  it("never fabricates a connectivity state when it isn't known yet", () => {
    expect(connectivityLabel(null)).toBe("Unknown");
  });
});
