import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { BillingStatus, FeatureMatrix } from "@mykhaya/shared-types";
import { HomeAccessProvider, useHomeAccess } from "./home-access";

let activeHomeId: string | null = "home-1";
let authStatus = "ready";
vi.mock("./auth-provider", () => ({ useAuth: () => ({ status: authStatus }) }));
vi.mock("./use-active-home", () => ({
  useActiveHome: () => ({ activeHomeId, activeHome: activeHomeId ? { id: activeHomeId } : null }),
}));

vi.mock("@mykhaya/api-client", () => ({
  api: { billingStatus: vi.fn(), featureMatrix: vi.fn() },
}));
const { api } = await import("@mykhaya/api-client");
const billingStatus = api.billingStatus as unknown as ReturnType<typeof vi.fn>;
const featureMatrix = api.featureMatrix as unknown as ReturnType<typeof vi.fn>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const matrix = { features: [] } as unknown as FeatureMatrix;
const billing = (family: boolean) => ({ family_access: family }) as unknown as BillingStatus;

function Probe() {
  const { access, refresh } = useHomeAccess();
  return (
    <>
      <div data-testid="state">
        {access.state === "ready" ? `ready:${access.value.billing.family_access}` : access.state}
      </div>
      <button onClick={() => void refresh()}>refresh</button>
    </>
  );
}

beforeEach(() => {
  activeHomeId = "home-1";
  authStatus = "ready";
  billingStatus.mockReset();
  featureMatrix.mockReset();
  featureMatrix.mockResolvedValue(matrix);
});

describe("HomeAccessProvider", () => {
  it("is loading — not allowed or denied — until billing AND features have both resolved", async () => {
    const b = deferred<BillingStatus>();
    billingStatus.mockReturnValue(b.promise);
    render(
      <HomeAccessProvider>
        <Probe />
      </HomeAccessProvider>,
    );

    await waitFor(() => expect(featureMatrix).toHaveBeenCalled());
    expect(screen.getByTestId("state")).toHaveTextContent("loading");
    await act(async () => b.resolve(billing(true)));
    expect(screen.getByTestId("state")).toHaveTextContent("ready:true");
  });

  it("reports error (not a guessed state) when resolution fails", async () => {
    billingStatus.mockRejectedValue(new Error("down"));
    render(
      <HomeAccessProvider>
        <Probe />
      </HomeAccessProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("error"));
  });

  it("never exposes another Home's access, and reuses a resolved Home instantly when switching back", async () => {
    billingStatus.mockImplementation((id: string) => Promise.resolve(billing(id === "home-1")));
    const { rerender } = render(
      <HomeAccessProvider>
        <Probe />
      </HomeAccessProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("ready:true"));

    const slow = deferred<BillingStatus>();
    billingStatus.mockReturnValue(slow.promise);
    activeHomeId = "home-2";
    rerender(
      <HomeAccessProvider>
        <Probe />
      </HomeAccessProvider>,
    );
    expect(screen.getByTestId("state")).toHaveTextContent("loading");
    await act(async () => slow.resolve(billing(false)));
    expect(screen.getByTestId("state")).toHaveTextContent("ready:false");

    billingStatus.mockReturnValue(new Promise(() => {}));
    activeHomeId = "home-1";
    rerender(
      <HomeAccessProvider>
        <Probe />
      </HomeAccessProvider>,
    );
    // Cached: no loading state even though revalidation is still in flight.
    expect(screen.getByTestId("state")).toHaveTextContent("ready:true");
  });

  it("keeps the last resolved access when a background revalidation fails", async () => {
    billingStatus.mockResolvedValueOnce(billing(true));
    render(
      <HomeAccessProvider>
        <Probe />
      </HomeAccessProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("ready:true"));

    billingStatus.mockRejectedValue(new Error("blip"));
    await act(async () => screen.getByText("refresh").click());
    expect(screen.getByTestId("state")).toHaveTextContent("ready:true");
  });

  it("picks up a plan change on refresh without passing through loading", async () => {
    billingStatus.mockResolvedValueOnce(billing(false));
    render(
      <HomeAccessProvider>
        <Probe />
      </HomeAccessProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("ready:false"));

    billingStatus.mockResolvedValue(billing(true));
    await act(async () => screen.getByText("refresh").click());
    expect(screen.getByTestId("state")).toHaveTextContent("ready:true");
  });

  it("drops all cached access when the session ends, and discards in-flight responses", async () => {
    billingStatus.mockResolvedValueOnce(billing(true));
    const { rerender } = render(
      <HomeAccessProvider>
        <Probe />
      </HomeAccessProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("ready:true"));

    authStatus = "signed_out";
    rerender(
      <HomeAccessProvider>
        <Probe />
      </HomeAccessProvider>,
    );
    expect(screen.getByTestId("state")).toHaveTextContent("loading");

    // A later session starts from nothing, never the previous one's plan.
    const slow = deferred<BillingStatus>();
    billingStatus.mockReturnValue(slow.promise);
    authStatus = "ready";
    rerender(
      <HomeAccessProvider>
        <Probe />
      </HomeAccessProvider>,
    );
    expect(screen.getByTestId("state")).toHaveTextContent("loading");
    await act(async () => slow.resolve(billing(false)));
    expect(screen.getByTestId("state")).toHaveTextContent("ready:false");
  });
});
