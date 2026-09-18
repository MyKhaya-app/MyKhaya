import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ControlCentreLayout from "./layout";

describe("Control Centre route layout", () => {
  it("renders its children without adding another shell or provider", () => {
    render(
      <ControlCentreLayout>
        <p>Control Centre content</p>
      </ControlCentreLayout>,
    );

    expect(screen.getByText("Control Centre content")).toBeInTheDocument();
    expect(document.querySelector(".platform-shell")).toBeNull();
    expect(document.querySelector(".pcc-root")).toBeNull();
  });
});
