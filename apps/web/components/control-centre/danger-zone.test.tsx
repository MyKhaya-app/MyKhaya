import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CcDangerZone } from "./danger-zone";

describe("CcDangerZone", () => {
  it("renders the default title and the given children", () => {
    render(
      <CcDangerZone>
        <button>Delete Home</button>
      </CcDangerZone>,
    );
    expect(screen.getByText("Danger zone")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete Home" })).toBeInTheDocument();
  });

  it("renders a custom title and description", () => {
    render(
      <CcDangerZone title="Irreversible actions" description="These cannot be undone.">
        <button>Delete</button>
      </CcDangerZone>,
    );
    expect(screen.getByText("Irreversible actions")).toBeInTheDocument();
    expect(screen.getByText("These cannot be undone.")).toBeInTheDocument();
  });

  it("uses the danger-zone visual treatment", () => {
    const { container } = render(
      <CcDangerZone>
        <button>Delete</button>
      </CcDangerZone>,
    );
    expect(container.querySelector("section")?.className).toContain("danger-zone");
  });
});
