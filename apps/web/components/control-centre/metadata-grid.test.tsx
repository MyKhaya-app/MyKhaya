import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CcMetadataGrid, CcMetadataItem } from "./metadata-grid";

describe("CcMetadataGrid", () => {
  it("renders label/value pairs as dt/dd", () => {
    render(
      <CcMetadataGrid>
        <CcMetadataItem label="Home ID">abc-123</CcMetadataItem>
        <CcMetadataItem label="Members">4</CcMetadataItem>
      </CcMetadataGrid>,
    );
    expect(screen.getByText("Home ID").tagName).toBe("DT");
    expect(screen.getByText("abc-123").tagName).toBe("DD");
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("marks a spanning item with the span class", () => {
    render(
      <CcMetadataGrid>
        <CcMetadataItem label="Note" span>
          Long internal note text
        </CcMetadataItem>
      </CcMetadataGrid>,
    );
    const dt = screen.getByText("Note");
    expect(dt.parentElement?.className).toContain("cc-metadata-item-span");
  });

  it("defaults to the auto-fit column layout", () => {
    const { container } = render(
      <CcMetadataGrid>
        <CcMetadataItem label="A">1</CcMetadataItem>
      </CcMetadataGrid>,
    );
    expect(container.querySelector("dl")?.className).not.toContain("cc-metadata-grid-2col");
  });

  it("applies the fixed two-column layout when requested", () => {
    const { container } = render(
      <CcMetadataGrid columns="fixed-2">
        <CcMetadataItem label="A">1</CcMetadataItem>
      </CcMetadataGrid>,
    );
    expect(container.querySelector("dl")?.className).toContain("cc-metadata-grid-2col");
  });
});
