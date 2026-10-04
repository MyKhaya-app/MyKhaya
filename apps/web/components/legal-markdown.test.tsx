import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LegalMarkdown } from "./legal-markdown";

describe("LegalMarkdown", () => {
  it("renders headings, lists and links from Markdown", () => {
    render(
      <LegalMarkdown
        content={"# Terms\n\n- One\n- Two\n\n[MyKhaya](https://mykhaya.example)"}
        className="legal-prose"
      />,
    );
    expect(screen.getByRole("heading", { name: "Terms" })).toBeInTheDocument();
    expect(screen.getByText("One")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "MyKhaya" })).toHaveAttribute(
      "href",
      "https://mykhaya.example",
    );
  });

  it("strips script tags and event-handler attributes from embedded HTML", () => {
    render(
      <LegalMarkdown
        content={'Safe text.\n\n<script>alert(1)</script>\n\n<div onclick="alert(1)">click</div>'}
        className="legal-prose"
      />,
    );
    expect(screen.getByText("Safe text.")).toBeInTheDocument();
    expect(document.querySelector("script")).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("onclick");
    expect(document.body.innerHTML).not.toContain("alert(1)</script>");
  });

  it("strips images entirely, since a legal document never needs one", () => {
    render(
      <LegalMarkdown
        content={'![tracker](https://example.com/pixel.gif "x")'}
        className="legal-prose"
      />,
    );
    expect(document.querySelectorAll("img")).toHaveLength(0);
  });
});
