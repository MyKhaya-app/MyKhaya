import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CcToolbar } from "./toolbar";

describe("CcToolbar", () => {
  it("renders only what it is given", () => {
    render(
      <CcToolbar>
        <button>Create</button>
      </CcToolbar>,
    );
    expect(screen.getByRole("button", { name: "Create" })).toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("uses the cc-toolbar layout class", () => {
    const { container } = render(
      <CcToolbar>
        <button>Create</button>
      </CcToolbar>,
    );
    expect(container.firstElementChild?.className).toBe("cc-toolbar");
  });
});
