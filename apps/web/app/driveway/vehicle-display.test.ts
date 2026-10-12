import { describe, expect, it } from "vitest";
import type { VehicleMotTest } from "@mykhaya/shared-types";
import {
  checkedAgo,
  daysUntil,
  formatMake,
  formatMileage,
  formatPlate,
  formatShortDate,
  joinWithAnd,
  milesBetweenTests,
  motDaysText,
  motListLabel,
  motPillLabel,
  motShortLabel,
  motState,
  testSummary,
  vehicleName,
} from "./vehicle-display";

const TODAY = new Date(2026, 9, 12); // 12 Oct 2026, local time

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

describe("MOT status rule (shared by every Driveway screen)", () => {
  it("is valid above 30 days, red from 30 days down to the day, and expired after", () => {
    expect(motState("valid", "2026-11-12", TODAY).tone).toBe("valid"); // 31 days
    expect(motState("valid", "2026-11-11", TODAY).tone).toBe("soon"); // 30 days
    expect(motState("valid", "2026-10-12", TODAY).tone).toBe("soon"); // today
    expect(motState("expired", "2026-10-11", TODAY).tone).toBe("expired");
    expect(motState("no_record", null, TODAY).tone).toBe("none");
    expect(motState(null, null, TODAY).tone).toBe("none");
  });

  it("words each state for the pill, the list and the history card", () => {
    const valid = motState("valid", "2027-08-25", TODAY);
    expect(motPillLabel(valid)).toBe("MOT valid");
    expect(motListLabel(valid)).toBe("MOT valid · 25 Aug 2027");
    expect(motShortLabel(valid)).toBe("Valid");
    expect(motDaysText(valid)).toBe("317 days left");

    const one = motState("valid", "2026-10-13", TODAY);
    expect(motPillLabel(one)).toBe("MOT due in 1 day");
    expect(motShortLabel(one)).toBe("Due in 1 day");
    expect(motDaysText(one)).toBe("1 day left");

    const expired = motState("expired", "2026-10-08", TODAY);
    expect(motPillLabel(expired)).toBe("MOT expired");
    expect(motDaysText(expired)).toBe("Expired 4 days ago");

    expect(motPillLabel(motState("no_record", null, TODAY))).toBe("No MOT record found");
    expect(motPillLabel(motState(null, null, TODAY))).toBe("MOT not checked yet");
  });

  it("counts whole calendar days", () => {
    expect(daysUntil("2026-10-12", new Date(2026, 9, 12, 23, 59))).toBe(0);
    expect(daysUntil("2027-08-25", TODAY)).toBe(317);
  });
});

describe("Driveway formatting", () => {
  it("formats dates as D Mon YYYY, never 'Sept'", () => {
    expect(formatShortDate("2027-08-25")).toBe("25 Aug 2027");
    expect(formatShortDate("2026-09-04")).toBe("4 Sep 2026");
    expect(formatShortDate(null)).toBeNull();
  });

  it("spaces standard UK plates only", () => {
    expect(formatPlate("ap22ooj")).toBe("AP22 OOJ");
    expect(formatPlate("AP22 OOJ")).toBe("AP22 OOJ");
    expect(formatPlate("DEV2BTEST2")).toBe("DEV2BTEST2");
    expect(formatPlate("A1 BCD")).toBe("A1 BCD");
    expect(formatPlate(null)).toBeNull();
  });

  it("names vehicles by make + model with correct casing", () => {
    expect(formatMake("Bmw")).toBe("BMW");
    expect(formatMake("MERCEDES-BENZ")).toBe("Mercedes-Benz");
    expect(formatMake("land rover")).toBe("Land Rover");
    expect(formatMake("McLaren")).toBe("McLaren");
    expect(vehicleName({ make: "BMW", model: "i4", nickname: "Family car" })).toBe("BMW i4");
    expect(vehicleName({ make: null, model: null, nickname: "My vehicle" })).toBe("My vehicle");
  });

  it("formats mileage with separators and units", () => {
    expect(formatMileage(test({ odometer_value: 51950, odometer_unit: "mi" }))).toBe("51,950 mi");
    expect(formatMileage(test({ odometer_value: 51950, odometer_unit: "mi" }), true)).toBe("51,950 miles");
    expect(formatMileage(test({ odometer_value: 30001, odometer_unit: "km" }), true)).toBe("30,001 km");
    expect(formatMileage(test({}))).toBeNull();
  });

  it("works out miles between the last two readings in the same unit", () => {
    expect(milesBetweenTests([test({ odometer_value: 51950, odometer_unit: "mi" }), test({ odometer_value: 37064, odometer_unit: "mi" })])).toBe(14886);
    expect(milesBetweenTests([test({ odometer_value: 100, odometer_unit: "mi" }), test({ odometer_value: 90, odometer_unit: "km" })])).toBeNull();
    expect(milesBetweenTests([test({ odometer_value: 100, odometer_unit: "mi" })])).toBeNull();
  });

  it("summarises a test's defects plainly", () => {
    expect(testSummary(test({}))).toBe("no defects or advisories");
    expect(
      testSummary(
        test({
          defects: [
            { text: "a", category: "advisory", dangerous: false },
            { text: "b", category: "advisory", dangerous: false },
            { text: "c", category: "major", dangerous: false },
          ],
        }),
      ),
    ).toBe("1 failure · 2 advisories");
  });

  it("describes when MOT data was checked and joins date lists naturally", () => {
    const now = new Date("2026-10-12T12:00:00Z");
    expect(checkedAgo("2026-10-12T11:57:00Z", now)).toBe("3 min ago");
    expect(checkedAgo("2026-10-12T11:59:40Z", now)).toBe("just now");
    expect(joinWithAnd(["A"])).toBe("A");
    expect(joinWithAnd(["A", "B"])).toBe("A and B");
    expect(joinWithAnd(["A", "B", "C"])).toBe("A, B and C");
  });
});
