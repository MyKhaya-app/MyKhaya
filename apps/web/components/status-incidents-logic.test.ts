import { describe, expect, it } from "vitest";
import {
  formatDuration,
  lifecycleStateLabel,
  lifecycleStateTone,
  serviceStateLabel,
  serviceStateTone,
} from "./status-incidents-logic";

describe("serviceStateLabel / serviceStateTone", () => {
  it("labels every ServiceState value", () => {
    expect(serviceStateLabel("operational")).toBe("Operational");
    expect(serviceStateLabel("degraded_performance")).toBe("Degraded Performance");
    expect(serviceStateLabel("partial_outage")).toBe("Partial Outage");
    expect(serviceStateLabel("major_outage")).toBe("Major Outage");
    expect(serviceStateLabel("maintenance")).toBe("Maintenance");
  });

  it("gives major/partial outage a danger tone and operational a success tone", () => {
    expect(serviceStateTone("operational")).toBe("success");
    expect(serviceStateTone("major_outage")).toBe("danger");
    expect(serviceStateTone("partial_outage")).toBe("danger");
    expect(serviceStateTone("degraded_performance")).toBe("warning");
    expect(serviceStateTone("maintenance")).toBe("info");
  });
});

describe("lifecycleStateLabel / lifecycleStateTone", () => {
  it("labels every incident lifecycle state", () => {
    expect(lifecycleStateLabel("investigating")).toBe("Investigating");
    expect(lifecycleStateLabel("identified")).toBe("Identified");
    expect(lifecycleStateLabel("monitoring")).toBe("Monitoring");
    expect(lifecycleStateLabel("resolved")).toBe("Resolved");
  });

  it("gives resolved a success tone and investigating a danger tone", () => {
    expect(lifecycleStateTone("resolved")).toBe("success");
    expect(lifecycleStateTone("investigating")).toBe("danger");
  });
});

describe("formatDuration", () => {
  it("formats a sub-hour duration as minutes only", () => {
    const start = "2026-01-01T10:00:00Z";
    const end = "2026-01-01T10:08:00Z";
    expect(formatDuration(start, end)).toBe("8m");
  });

  it("formats an exact-hour duration without a minutes component", () => {
    const start = "2026-01-01T10:00:00Z";
    const end = "2026-01-01T12:00:00Z";
    expect(formatDuration(start, end)).toBe("2h");
  });

  it("formats a mixed hours-and-minutes duration", () => {
    const start = "2026-01-01T10:00:00Z";
    const end = "2026-01-01T11:24:00Z";
    expect(formatDuration(start, end)).toBe("1h 24m");
  });

  it("never returns a negative duration", () => {
    const start = "2026-01-01T10:00:00Z";
    const end = "2026-01-01T09:00:00Z";
    expect(formatDuration(start, end)).toBe("0m");
  });
});
