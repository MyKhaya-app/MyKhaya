import { describe, expect, it } from "vitest";
import { consumerRouteMetadata } from "./consumer-route-metadata";

describe("consumerRouteMetadata", () => {
  it("leaves primary navigation roots without a Back fallback", () => {
    expect(consumerRouteMetadata("/home")).toEqual({});
    expect(consumerRouteMetadata("/calendar")).toEqual({});
    expect(consumerRouteMetadata("/people")).toEqual({});
    expect(consumerRouteMetadata("/settings")).toEqual({});
  });

  it("provides safe in-app fallbacks for direct links", () => {
    expect(consumerRouteMetadata("/lists/list-1")).toEqual({ backFallback: "/lists" });
    expect(consumerRouteMetadata("/driveway/v-1")).toEqual({ backFallback: "/driveway" });
    expect(consumerRouteMetadata("/driveway/v-1/mot")).toEqual({ backFallback: "/driveway/v-1" });
    expect(consumerRouteMetadata("/driveway/add")).toEqual({ backFallback: "/driveway" });
    expect(consumerRouteMetadata("/help-support/requests/t-1")).toEqual({ backFallback: "/help-support/requests" });
  });
});
