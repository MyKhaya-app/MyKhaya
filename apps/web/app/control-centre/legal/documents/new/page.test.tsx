import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NewLegalDocumentPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/legal/documents/new",
  useRouter: () => ({ push, replace: vi.fn() }),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, platformApi: { get: vi.fn(), post: vi.fn() } };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue(null);
});

describe("New legal document", () => {
  it("rejects a key that doesn't match the allowed pattern", async () => {
    render(<NewLegalDocumentPage />);
    await userEvent.type(screen.getByLabelText(/^Key/), "Not Valid!");
    await userEvent.type(screen.getByLabelText("Display name"), "Terms");
    await userEvent.click(screen.getByRole("button", { name: "Create document" }));
    expect(
      await screen.findByText(/Key must start with a lowercase letter/),
    ).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("submits the exact payload shape and navigates to the created document", async () => {
    post.mockResolvedValue({ id: "doc-9" });
    render(<NewLegalDocumentPage />);
    await userEvent.type(screen.getByLabelText(/^Key/), "children_privacy");
    await userEvent.type(screen.getByLabelText("Display name"), "Family & Children's Privacy Notice");
    await userEvent.selectOptions(screen.getByLabelText("Audience"), "child");
    await userEvent.click(screen.getByRole("button", { name: "Create document" }));
    await Promise.resolve();
    expect(post).toHaveBeenCalledWith("/legal/documents", {
      key: "children_privacy",
      display_name: "Family & Children's Privacy Notice",
      audience: "child",
      action_verb: "accept",
      acceptance_required: true,
    });
    expect(push).toHaveBeenCalledWith("/legal/documents/doc-9");
  });

  it("shows a safe error message when creation fails", async () => {
    post.mockRejectedValue(new ApiError(409, "A legal document with that key already exists."));
    render(<NewLegalDocumentPage />);
    await userEvent.type(screen.getByLabelText(/^Key/), "terms");
    await userEvent.type(screen.getByLabelText("Display name"), "Terms");
    await userEvent.click(screen.getByRole("button", { name: "Create document" }));
    expect(
      await screen.findByText("A legal document with that key already exists."),
    ).toBeInTheDocument();
  });
});
