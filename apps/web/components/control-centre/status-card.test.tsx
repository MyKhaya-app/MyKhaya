import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PowerOff } from "lucide-react";
import { CcStatusCard } from "./status-card";

describe("CcStatusCard", () => {
  it("renders the status headline", () => {
    render(<CcStatusCard tone="success" status="Enabled" />);
    expect(screen.getByText("Enabled")).toBeInTheDocument();
  });

  it("renders an optional description blurb", () => {
    render(
      <CcStatusCard tone="danger" status="Disabled" description="This account cannot sign in." />,
    );
    expect(screen.getByText("This account cannot sign in.")).toBeInTheDocument();
  });

  it("renders supporting key/value items as a definition list", () => {
    render(
      <CcStatusCard
        tone="neutral"
        status="Enabled"
        items={[
          { label: "Expiry", value: "12 Sep 2026" },
          { label: "Access", value: "Full" },
        ]}
      />,
    );
    expect(screen.getByText("Expiry").tagName).toBe("DT");
    expect(screen.getByText("12 Sep 2026").tagName).toBe("DD");
    expect(screen.getByText("Access")).toBeInTheDocument();
    expect(screen.getByText("Full")).toBeInTheDocument();
  });

  it("omits the items list entirely when none are given", () => {
    const { container } = render(<CcStatusCard tone="neutral" status="Enabled" />);
    expect(container.querySelector("dl")).toBeNull();
  });

  it("renders extra children below the items", () => {
    render(
      <CcStatusCard tone="neutral" status="Enabled">
        <p>Extra context</p>
      </CcStatusCard>,
    );
    expect(screen.getByText("Extra context")).toBeInTheDocument();
  });

  it("defaults to the neutral tone", () => {
    render(<CcStatusCard status="Unknown" />);
    const card = screen.getByText("Unknown").closest(".cc-status-card");
    expect(card?.className).toContain("cc-status-card-neutral");
  });

  it("lets a caller override the tone-derived icon", () => {
    const { container } = render(<CcStatusCard tone="neutral" status="Disabled" icon={PowerOff} />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
