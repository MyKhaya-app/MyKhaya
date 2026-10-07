import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PlatformShell } from "./platform-shell";

// Exercises the real administrator-session resolution, not the authenticated
// default from vitest.setup.ts.
vi.unmock("@/components/platform-session");
vi.unmock("./components/platform-session");

const router = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/users",
  useRouter: () => router,
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, platformApi: { get: vi.fn(), post: vi.fn() } };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;

const actor = (session_status = "full") => ({
  id: "op-1",
  email: "op@example.com",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status,
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

// Records every render of the protected child so a test can prove it was
// NEVER rendered, not merely absent at the end.
function renderShell() {
  const rendered = vi.fn();
  function Protected() {
    rendered();
    return <p>Protected PCC content</p>;
  }
  const view = render(
    <PlatformShell>
      <Protected />
    </PlatformShell>,
  );
  return { ...view, rendered };
}

beforeEach(() => {
  get.mockReset();
  router.replace.mockReset();
  window.localStorage.clear();
});

describe("PlatformShell session gate", () => {
  it("renders no PCC chrome or content while the session is resolving", async () => {
    const me = deferred<unknown>();
    get.mockReturnValue(me.promise);
    const { rendered, container } = renderShell();

    expect(rendered).not.toHaveBeenCalled();
    expect(screen.queryByText("Protected PCC content")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Control Centre navigation" })).not.toBeInTheDocument();
    expect(container.querySelector(".platform-shell")).toBeNull();
    expect(router.replace).not.toHaveBeenCalled();
    await act(async () => me.resolve(actor()));
  });

  it("never renders protected content for a signed-out visitor, and redirects to login", async () => {
    get.mockRejectedValue(new ApiError(401, "Not authenticated"));
    const { rendered } = renderShell();

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(rendered).not.toHaveBeenCalled();
    expect(screen.queryByText("Protected PCC content")).not.toBeInTheDocument();
    expect(screen.queryByText("Operator One")).not.toBeInTheDocument();
  });

  it("sends a mid-MFA session to its next step without rendering content", async () => {
    get.mockResolvedValue(actor("mfa_setup_required"));
    const { rendered } = renderShell();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/setup-mfa"));
    expect(rendered).not.toHaveBeenCalled();
  });

  it("renders the shell and content once authenticated", async () => {
    get.mockResolvedValue(actor());
    renderShell();
    expect(await screen.findByText("Protected PCC content")).toBeInTheDocument();
    expect(screen.getByText("Operator One")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("reuses the resolved session on the next navigation — no gate, no loading state", async () => {
    get.mockResolvedValue(actor());
    const first = renderShell();
    await screen.findByText("Protected PCC content");
    first.unmount();

    // A second page mounts its own shell; the session is already known.
    get.mockReturnValue(new Promise(() => {}));
    renderShell();
    expect(screen.getByText("Protected PCC content")).toBeInTheDocument();
    expect(screen.getByText("Operator One")).toBeInTheDocument();
  });

  it("falls back to the gate and redirects when a cached session has expired", async () => {
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(1_000_000);
    get.mockResolvedValue(actor());
    const first = renderShell();
    await screen.findByText("Protected PCC content");
    first.unmount();

    now.mockReturnValue(1_000_000 + 60_000);
    get.mockRejectedValue(new ApiError(401, "Session expired"));
    renderShell();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    await waitFor(() => expect(screen.queryByText("Protected PCC content")).not.toBeInTheDocument());
    now.mockRestore();
  });

  it("treats a network/server failure as 'could not verify', not signed-out, and can retry", async () => {
    const user = userEvent.setup();
    get.mockRejectedValue(new Error("network"));
    const { rendered } = renderShell();

    expect(await screen.findByText("The Control Centre could not verify your session.")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
    expect(rendered).not.toHaveBeenCalled();

    get.mockResolvedValue(actor());
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Protected PCC content")).toBeInTheDocument();
  });

  it("does not turn a maintenance 503 into the consumer maintenance surface", async () => {
    get.mockRejectedValue(new ApiError(503, "Maintenance", "maintenance_mode"));
    const { rendered } = renderShell();

    expect(await screen.findByText("The Control Centre could not verify your session.")).toBeInTheDocument();
    expect(rendered).not.toHaveBeenCalled();
    expect(screen.queryByTestId("maintenance-screen")).not.toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("does not paint protected UI from a stale cached session before the server answers", async () => {
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(1_000_000);
    get.mockResolvedValue(actor());
    const first = renderShell();
    await screen.findByText("Protected PCC content");
    first.unmount();

    // Past the TTL, the session has silently expired; the check is slow.
    now.mockReturnValue(1_000_000 + 60_000);
    const check = deferred<unknown>();
    get.mockReturnValue(check.promise);
    const second = renderShell();
    expect(second.rendered).not.toHaveBeenCalled();
    expect(screen.queryByText("Protected PCC content")).not.toBeInTheDocument();
    expect(screen.queryByText("Operator One")).not.toBeInTheDocument();
    await act(async () => check.resolve(actor()));
    expect(await screen.findByText("Protected PCC content")).toBeInTheDocument();
    now.mockRestore();
  });

  it("forgets the session on sign-out so the next shell must re-resolve", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue(actor());
    (platformApi.post as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
    const first = renderShell();
    await screen.findByText("Protected PCC content");
    await user.click(screen.getByRole("button", { name: /sign out/i }));
    first.unmount();

    get.mockReturnValue(new Promise(() => {}));
    const second = renderShell();
    expect(second.rendered).not.toHaveBeenCalled();
    expect(screen.queryByText("Operator One")).not.toBeInTheDocument();
  });
});
