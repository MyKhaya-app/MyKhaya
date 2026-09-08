import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Onboarding from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => false,
}));
const nativeLogout = vi.fn<() => Promise<void>>();
vi.mock("@/components/native-auth", () => ({
  nativeLogout: () => nativeLogout(),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      post: vi.fn(),
      familyPricing: vi.fn(),
      createCheckoutSession: vi.fn(),
      lookupHomeJoinCode: vi.fn(),
      requestHomeJoin: vi.fn(),
    },
  };
});

const { api, ApiError } = await import("@mykhaya/api-client");
const post = api.post as unknown as ReturnType<typeof vi.fn>;
const lookupHomeJoinCode = api.lookupHomeJoinCode as unknown as ReturnType<typeof vi.fn>;
const requestHomeJoin = api.requestHomeJoin as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("Onboarding — Join/Create choice", () => {
  it("shows both Join and Create as equally visible primary choices by default", () => {
    render(<Onboarding />);
    expect(screen.getByText("How would you like to use MyKhaya?")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Join an existing Home" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create a new Home" })).toBeInTheDocument();
    expect(screen.getByText(/already has a MyKhaya Home/)).toBeInTheDocument();
  });

  it("does not call any Home-creation or Home-join API just by rendering the choice screen", () => {
    render(<Onboarding />);
    expect(post).not.toHaveBeenCalled();
    expect(lookupHomeJoinCode).not.toHaveBeenCalled();
  });

  it("lets a Home-less account sign out directly from the choice screen", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue({});
    render(<Onboarding />);
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/auth/logout", {}));
    expect(push).toHaveBeenCalledWith("/login");
  });
});

describe("Onboarding — Create a new Home", () => {
  it("choosing Create follows the existing Home-creation flow, unchanged", async () => {
    const user = userEvent.setup();
    render(<Onboarding />);
    await user.click(screen.getByRole("button", { name: "Create a new Home" }));

    expect(screen.getByText("What do you call home?")).toBeInTheDocument();
    expect(screen.getByLabelText("Home name")).toBeInTheDocument();
  });

  it("Back from the Create step returns to the choice screen", async () => {
    const user = userEvent.setup();
    render(<Onboarding />);
    await user.click(screen.getByRole("button", { name: "Create a new Home" }));
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("How would you like to use MyKhaya?")).toBeInTheDocument();
  });
});

describe("Onboarding — Join an existing Home", () => {
  it("choosing Join does not create a Home", async () => {
    const user = userEvent.setup();
    render(<Onboarding />);
    await user.click(screen.getByRole("button", { name: "Join an existing Home" }));

    expect(screen.getByRole("heading", { name: "Join an existing Home" })).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("looks up the Home by code and shows its identity before requesting to join", async () => {
    const user = userEvent.setup();
    lookupHomeJoinCode.mockResolvedValue({ group_id: "home-1", group_name: "Hales Home" });
    render(<Onboarding />);
    await user.click(screen.getByRole("button", { name: "Join an existing Home" }));
    await user.type(screen.getByLabelText("Home join code"), "K7P4-X2RM");
    await user.click(screen.getByRole("button", { name: "Find Home" }));

    await waitFor(() => expect(lookupHomeJoinCode).toHaveBeenCalledWith("K7P4-X2RM"));
    expect(await screen.findByRole("heading", { name: "Hales Home" })).toBeInTheDocument();
    expect(screen.getByText(/A Home Admin will need to approve your request/)).toBeInTheDocument();
    // Finding the Home never itself creates a request/membership.
    expect(requestHomeJoin).not.toHaveBeenCalled();
  });

  it("shows a safe error for an unrecognised code without crashing the flow", async () => {
    const user = userEvent.setup();
    lookupHomeJoinCode.mockRejectedValue(
      new ApiError(404, "That Home join code was not recognised."),
    );
    render(<Onboarding />);
    await user.click(screen.getByRole("button", { name: "Join an existing Home" }));
    await user.type(screen.getByLabelText("Home join code"), "ZZZZ-ZZZZ");
    await user.click(screen.getByRole("button", { name: "Find Home" }));

    expect(await screen.findByText("That Home join code was not recognised.")).toBeInTheDocument();
  });

  it("submits the join request only after the operator explicitly confirms", async () => {
    const user = userEvent.setup();
    lookupHomeJoinCode.mockResolvedValue({ group_id: "home-1", group_name: "Hales Home" });
    requestHomeJoin.mockResolvedValue({ id: "req-1", group_id: "home-1", status: "pending", created_at: "2026-01-01T00:00:00Z" });
    render(<Onboarding />);
    await user.click(screen.getByRole("button", { name: "Join an existing Home" }));
    await user.type(screen.getByLabelText("Home join code"), "K7P4-X2RM");
    await user.click(screen.getByRole("button", { name: "Find Home" }));
    await screen.findByRole("heading", { name: "Hales Home" });
    expect(requestHomeJoin).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Request to join" }));
    await waitFor(() => expect(requestHomeJoin).toHaveBeenCalledWith("K7P4-X2RM"));
    expect(await screen.findByText("Request sent")).toBeInTheDocument();
  });

  it("account stays authenticated and Home-less after a request is sent — no forced Home is created", async () => {
    const user = userEvent.setup();
    lookupHomeJoinCode.mockResolvedValue({ group_id: "home-1", group_name: "Hales Home" });
    requestHomeJoin.mockResolvedValue({ id: "req-1", group_id: "home-1", status: "pending", created_at: "2026-01-01T00:00:00Z" });
    render(<Onboarding />);
    await user.click(screen.getByRole("button", { name: "Join an existing Home" }));
    await user.type(screen.getByLabelText("Home join code"), "K7P4-X2RM");
    await user.click(screen.getByRole("button", { name: "Find Home" }));
    await user.click(await screen.findByRole("button", { name: "Request to join" }));
    await screen.findByText("Request sent");

    expect(post).not.toHaveBeenCalledWith("/groups", expect.anything());
    // Still able to sign out normally from this state.
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(push).toHaveBeenCalledWith("/login");
  });
});
