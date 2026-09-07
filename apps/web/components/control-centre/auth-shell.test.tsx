import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CcAuthShell } from "./auth-shell";

describe("CcAuthShell", () => {
  it("renders the MyKhaya PCC brand mark and a kicker by default", () => {
    render(
      <CcAuthShell>
        <h1>Test heading</h1>
      </CcAuthShell>,
    );
    expect(screen.getByText("MyKhaya")).toBeInTheDocument();
    expect(screen.getByText("Platform Control Centre")).toBeInTheDocument();
    expect(screen.getByText("Restricted management plane")).toBeInTheDocument();
    expect(screen.getByText("Test heading")).toBeInTheDocument();
  });

  it("omits the kicker when explicitly passed null", () => {
    render(
      <CcAuthShell kicker={null}>
        <p role="status">Loading…</p>
      </CcAuthShell>,
    );
    expect(screen.queryByText("Restricted management plane")).not.toBeInTheDocument();
  });

  it("supports a custom kicker for a different auth context", () => {
    render(
      <CcAuthShell kicker="Custom context">
        <p>Body</p>
      </CcAuthShell>,
    );
    expect(screen.getByText("Custom context")).toBeInTheDocument();
  });
});
