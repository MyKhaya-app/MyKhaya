import { describe, expect, it } from "vitest";
import { vehicleFieldErrors, type VehicleFieldValues } from "./vehicle-fields";

// The checks Add vehicle and Edit details make before saving. They mirror
// the API's VehicleCreate contract; the API stays the authority.

const VALID: VehicleFieldValues = {
  countryCode: "GB",
  registration: "AP22 OOJ",
  ownerUserId: "u1",
  nickname: "BMW i4",
  make: "",
  model: "",
  year: "",
  fuelType: "",
  colour: "",
  firstRegistrationDate: "",
  engineSize: "",
  vin: "",
};
const ADD = { requireNickname: false, firstRegistrationDateUnreadable: false };
const EDIT = { requireNickname: true, firstRegistrationDateUnreadable: false };

describe("vehicleFieldErrors", () => {
  it("accepts a complete vehicle, with or without the optional fields", () => {
    expect(vehicleFieldErrors(VALID, ADD)).toEqual({});
    expect(vehicleFieldErrors({ ...VALID, year: "2022", firstRegistrationDate: "2022-03-01" }, EDIT)).toEqual({});
  });

  it("names each missing required field", () => {
    expect(vehicleFieldErrors({ ...VALID, countryCode: "", registration: "  ", ownerUserId: "" }, ADD)).toEqual({
      countryCode: "Choose the country or region the vehicle is registered in.",
      registration: "Add the registration.",
      ownerUserId: "Choose who the vehicle belongs to.",
    });
  });

  it("requires a nickname only where the page asks for one", () => {
    expect(vehicleFieldErrors({ ...VALID, nickname: "" }, ADD)).toEqual({});
    expect(vehicleFieldErrors({ ...VALID, nickname: " " }, EDIT)).toEqual({ nickname: "Add a nickname." });
  });

  it("keeps the year within the API's 1900–2200 range", () => {
    for (const year of ["1899", "2201", "20.5"]) {
      expect(vehicleFieldErrors({ ...VALID, year }, ADD)).toEqual({ year: "Enter a year between 1900 and 2200." });
    }
    expect(vehicleFieldErrors({ ...VALID, year: "1900" }, ADD)).toEqual({});
    expect(vehicleFieldErrors({ ...VALID, year: "2200" }, ADD)).toEqual({});
  });

  it("flags a first registration date the browser could not read", () => {
    expect(vehicleFieldErrors(VALID, { ...ADD, firstRegistrationDateUnreadable: true })).toEqual({
      firstRegistrationDate: "Enter a full date, or clear it.",
    });
  });
});
