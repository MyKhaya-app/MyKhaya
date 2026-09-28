import { afterEach, describe, expect, it, vi } from "vitest";
import { PlatformClient } from "./platform";

describe("PlatformClient validation errors", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders safe FastAPI field validation messages for a 422", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              { loc: ["body", "port"], msg: "Input should be less than or equal to 65535", type: "less_than_equal" },
              { loc: ["body", "reason"], msg: "String should have at least 10 characters", type: "string_too_short" },
            ],
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(new PlatformClient().put("/logging/syslog", {})).rejects.toThrow(
      "port: Input should be less than or equal to 65535 reason: String should have at least 10 characters",
    );
  });
});
