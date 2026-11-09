import { describe, expect, it } from "vitest";
import {
  alertKindLabel,
  alertKindTone,
  componentStateLabel,
  componentStateTone,
  deliverySummary,
  formatInterval,
  formatLatency,
  hasFailedDelivery,
  sortComponents,
  suppressionLabel,
  type AlertDelivery,
  type MonitorComponent,
} from "./monitoring-logic";

function delivery(status: string): AlertDelivery {
  return {
    attempt: "initial",
    recipient: "admin:1",
    channel: "email",
    status,
    attempted_at: null,
    retry_count: 0,
    failure_reason: null,
  };
}

describe("monitoring display logic", () => {
  it("never presents Unknown as healthy", () => {
    expect(componentStateLabel("unknown")).toBe("Unknown");
    expect(componentStateTone("unknown")).not.toBe("success");
    expect(componentStateLabel("not_applicable")).toBe("Not in use");
    expect(componentStateTone("unavailable")).toBe("danger");
  });

  it("labels alert kinds and suppression reasons", () => {
    expect(alertKindLabel("monitoring_stale")).toBe("Monitoring stopped");
    expect(alertKindTone("recovered")).toBe("success");
    expect(suppressionLabel("cooldown")).toContain("cooldown");
    expect(suppressionLabel(null)).toBeNull();
  });

  it("summarises delivery records honestly", () => {
    expect(deliverySummary([])).toBe("No email deliveries");
    expect(deliverySummary([delivery("failed"), delivery("sent"), delivery("sent")])).toBe(
      "2 sent · 1 failed",
    );
    expect(hasFailedDelivery([delivery("sent")])).toBe(false);
    expect(hasFailedDelivery([delivery("failed")])).toBe(true);
  });

  it("formats latency and intervals", () => {
    expect(formatLatency(null)).toBe("—");
    expect(formatLatency(240)).toBe("240 ms");
    expect(formatLatency(1500)).toBe("1.5 s");
    expect(formatInterval(60)).toBe("1 min");
    expect(formatInterval(300)).toBe("5 min");
    expect(formatInterval(45)).toBe("45 s");
  });

  it("sorts components needing attention first", () => {
    const base = { name: "x" } as MonitorComponent;
    const sorted = sortComponents([
      { ...base, key: "a", name: "A", state: "healthy" },
      { ...base, key: "b", name: "B", state: "unavailable" },
      { ...base, key: "c", name: "C", state: "unknown" },
    ]);
    expect(sorted.map((item) => item.key)).toEqual(["b", "c", "a"]);
  });
});
