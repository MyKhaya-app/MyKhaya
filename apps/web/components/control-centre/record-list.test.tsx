import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CcRecordCard, CcRecordList } from "./record-list";

describe("CcRecordCard", () => {
  it("renders the title, meta lines, and badge", () => {
    render(
      <CcRecordCard title="Jane Doe" meta={["jane@example.com", "Owner"]} badge="Active" badgeTone="success">
        <p>Extra note</p>
      </CcRecordCard>,
    );
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("jane@example.com")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Active").className).toContain("cc-badge-success");
    expect(screen.getByText("Extra note")).toBeInTheDocument();
  });

  it("renders actions when given", () => {
    render(<CcRecordCard title="Session" actions={<button>Revoke</button>} />);
    expect(screen.getByRole("button", { name: "Revoke" })).toBeInTheDocument();
  });

  it("omits the badge when none is given", () => {
    render(<CcRecordCard title="Note" />);
    expect(document.querySelector(".cc-badge")).toBeNull();
  });
});

describe("CcRecordList", () => {
  it("renders each child inside the record-list container", () => {
    render(
      <CcRecordList>
        <CcRecordCard title="First" />
        <CcRecordCard title="Second" />
      </CcRecordList>,
    );
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
    expect(document.querySelector(".record-list")).not.toBeNull();
  });

  it("shows the empty state instead of an empty container when given an empty array", () => {
    render(<CcRecordList emptyMessage="No sessions recorded yet.">{[]}</CcRecordList>);
    expect(screen.getByText("No sessions recorded yet.")).toBeInTheDocument();
    expect(document.querySelector(".record-list")).toBeNull();
  });

  it("falls back to a default empty message", () => {
    render(<CcRecordList>{[]}</CcRecordList>);
    expect(screen.getByText("No records yet.")).toBeInTheDocument();
  });

  it("renders a single non-array child normally", () => {
    render(
      <CcRecordList>
        <CcRecordCard title="Only one" />
      </CcRecordList>,
    );
    expect(screen.getByText("Only one")).toBeInTheDocument();
  });
});
