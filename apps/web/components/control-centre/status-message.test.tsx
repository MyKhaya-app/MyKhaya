import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CcEmptyState, CcErrorState, CcLoadingState, CcNotice } from "./status-message";

describe("CcNotice", () => {
  it("uses role alert for the error tone", () => {
    render(<CcNotice tone="error">Something went wrong.</CcNotice>);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong.");
  });

  it("uses role status for success and warning tones", () => {
    render(<CcNotice tone="success">Saved.</CcNotice>);
    expect(screen.getByRole("status")).toHaveTextContent("Saved.");
  });
});

describe("CcLoadingState", () => {
  it("renders a status role with the default label", () => {
    render(<CcLoadingState />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
  });

  it("accepts a custom label", () => {
    render(<CcLoadingState label="Loading managed Home…" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading managed Home…");
  });
});

describe("CcEmptyState", () => {
  it("renders the default message", () => {
    render(<CcEmptyState />);
    expect(screen.getByText("No results.")).toBeInTheDocument();
  });

  it("renders a custom message", () => {
    render(<CcEmptyState>No managed Demo/Test Homes.</CcEmptyState>);
    expect(screen.getByText("No managed Demo/Test Homes.")).toBeInTheDocument();
  });
});

describe("CcErrorState", () => {
  it("renders as an alert", () => {
    render(<CcErrorState>Unable to load this Home.</CcErrorState>);
    expect(screen.getByRole("alert")).toHaveTextContent("Unable to load this Home.");
  });
});
