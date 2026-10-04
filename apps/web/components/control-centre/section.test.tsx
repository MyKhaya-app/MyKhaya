import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CheckCircle2 } from "lucide-react";
import { CcSection, CcCard, CcColumns } from "./section";

describe("CcSection", () => {
  it("renders a title and description with the children", () => {
    render(
      <CcSection title="Home details" description="Everything about this Home.">
        <p>Body content</p>
      </CcSection>,
    );
    expect(screen.getByRole("heading", { name: "Home details" })).toBeInTheDocument();
    expect(screen.getByText("Everything about this Home.")).toBeInTheDocument();
    expect(screen.getByText("Body content")).toBeInTheDocument();
  });

  it("omits the heading row entirely when no title or actions are given", () => {
    const { container } = render(
      <CcSection>
        <p>Body content</p>
      </CcSection>,
    );
    expect(container.querySelector(".cc-section-heading")).toBeNull();
  });

  it("applies the danger tone class", () => {
    const { container } = render(
      <CcSection title="Danger zone" tone="danger">
        <p>Body</p>
      </CcSection>,
    );
    expect(container.querySelector(".cc-section-danger")).not.toBeNull();
  });
});

describe("CcCard", () => {
  it("renders children with no header when no title/actions are given", () => {
    const { container } = render(<CcCard>Plain content</CcCard>);
    expect(screen.getByText("Plain content")).toBeInTheDocument();
    expect(container.querySelector(".cc-card-header")).toBeNull();
  });

  it("renders an in-card header with icon, title, description and actions", () => {
    render(
      <CcCard
        title="Actions"
        description="Manage this test Home's state."
        icon={CheckCircle2}
        actions={<button>Refresh</button>}
      >
        <p>Card body</p>
      </CcCard>,
    );
    expect(screen.getByRole("heading", { name: "Actions" })).toBeInTheDocument();
    expect(screen.getByText("Manage this test Home's state.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(screen.getByText("Card body")).toBeInTheDocument();
  });
});

describe("CcColumns", () => {
  it("defaults to the 2-1 ratio", () => {
    const { container } = render(
      <CcColumns>
        <div>Left</div>
        <div>Right</div>
      </CcColumns>,
    );
    expect(container.querySelector(".cc-columns-2-1")).not.toBeNull();
  });

  it("supports the 1-1 ratio", () => {
    const { container } = render(
      <CcColumns ratio="1-1">
        <div>Left</div>
        <div>Right</div>
      </CcColumns>,
    );
    expect(container.querySelector(".cc-columns-1-1")).not.toBeNull();
  });
});
