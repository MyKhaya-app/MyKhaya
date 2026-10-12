import { describe, expect, it } from "vitest";
import type { VehicleMotSummary, VehicleMotTest } from "@mykhaya/shared-types";
import {
  formatMileage,
  groupDefects,
  motDateLine,
  motResultLabel,
  motStatusLabel,
  motStatusTone,
  relativeTime,
} from "./mot-format";

function summary(overrides: Partial<VehicleMotSummary>): VehicleMotSummary {
  return {
    status: null,
    due_date: null,
    expiry_date: null,
    first_mot_due_date: null,
    last_test_date: null,
    last_result: null,
    source: null,
    refreshed_at: null,
    stale: false,
    last_attempt_at: null,
    last_attempt_outcome: null,
    ...overrides,
  };
}

function test(overrides: Partial<VehicleMotTest>): VehicleMotTest {
  return {
    id: "t",
    test_number: null,
    test_date: "2026-09-01",
    completed_at: null,
    expiry_date: null,
    result: "passed",
    odometer_value: null,
    odometer_unit: null,
    odometer_result: null,
    defects: [],
    ...overrides,
  };
}

describe("MOT status wording", () => {
  it("maps normalised codes to family language, never raw codes", () => {
    expect(motStatusLabel("valid")).toBe("Valid");
    expect(motStatusLabel("expired")).toBe("Expired");
    expect(motStatusLabel("not_yet_due")).toBe("Not yet due");
    expect(motStatusLabel("no_record")).toBe("No MOT record");
    expect(motStatusLabel(null)).toBeNull();
  });

  it("gives each status a tone, with words always carrying the meaning", () => {
    expect(motStatusTone("valid")).toBe("good");
    expect(motStatusTone("not_yet_due")).toBe("good");
    expect(motStatusTone("expired")).toBe("warning");
    expect(motStatusTone("no_record")).toBe("neutral");
  });

  it("writes the date line for each state", () => {
    expect(motDateLine(summary({ status: "valid", due_date: "2027-03-14" }))).toBe("Expires 14 March 2027");
    expect(motDateLine(summary({ status: "expired", due_date: "2026-03-14" }))).toBe("Expired 14 March 2026");
    expect(motDateLine(summary({ status: "not_yet_due", due_date: "2028-03-14" }))).toBe("First MOT due 14 March 2028");
    expect(motDateLine(summary({ status: "no_record" }))).toBe("No MOT history found for this registration.");
    expect(motDateLine(summary({ status: null }))).toBeNull();
  });

  it("describes when data was last checked", () => {
    const now = new Date("2026-10-12T12:00:00Z");
    expect(relativeTime("2026-10-12T10:00:00Z", now)).toBe("2 hours ago");
    expect(relativeTime("2026-10-11T12:00:00Z", now)).toBe("yesterday");
    expect(relativeTime("2026-10-12T11:59:40Z", now)).toBe("just now");
    expect(relativeTime(null, now)).toBeNull();
  });
});

describe("MOT test presentation", () => {
  it("formats mileage with its unit, or explains a missing reading", () => {
    expect(formatMileage(test({ odometer_value: 45210, odometer_unit: "mi" }))).toBe("45,210 miles");
    expect(formatMileage(test({ odometer_value: 30001, odometer_unit: "km" }))).toBe("30,001 km");
    expect(formatMileage(test({ odometer_result: "no_odometer" }))).toBe("No odometer");
    expect(formatMileage(test({}))).toBeNull();
  });

  it("groups defects most-serious first, dangerous items leading, empty groups dropped", () => {
    const groups = groupDefects([
      { text: "Wiper blade deteriorated", category: "minor", dangerous: false },
      { text: "Headlamp aim too high", category: "major", dangerous: false },
      { text: "Brake pipe corroded", category: "dangerous", dangerous: true },
      { text: "Tyre close to limit", category: "advisory", dangerous: false },
    ]);
    expect(groups.map((g) => g.title)).toEqual(["Reasons for failure", "Minor defects", "Advisories"]);
    expect(groups[0]?.items.map((d) => d.text)).toEqual(["Brake pipe corroded", "Headlamp aim too high"]);
  });

  it("labels results plainly", () => {
    expect(motResultLabel("passed")).toBe("Passed");
    expect(motResultLabel("failed")).toBe("Failed");
    expect(motResultLabel("other")).toBe("Result unavailable");
  });
});
