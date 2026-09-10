import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Register from "./page";

const { push, post, nativeRegister, nativeShellState } = vi.hoisted(() => ({
  push: vi.fn(),
  post: vi.fn(),
  nativeRegister: vi.fn(),
  nativeShellState: { value: false },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => nativeShellState.value,
}));

vi.mock("@/components/native-auth", () => ({
  nativeRegister,
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      post,
    },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  nativeShellState.value = false;
  nativeRegister.mockResolvedValue({ message: "Check your inbox.", verification_required: true });
  post.mockResolvedValue({ message: "Check your inbox.", verification_required: true });
});

async function submitRegistration() {
  const user = userEvent.setup();
  render(<Register />);
  await user.type(screen.getByLabelText("Your name"), "New User");
  await user.type(screen.getByLabelText("Email"), "new@example.com");
  await user.type(
    screen.getByLabelText("Password", { exact: false, selector: 'input[name="password"]' }),
    "correct horse battery staple",
  );
  await user.type(screen.getByLabelText("Confirm password"), "correct horse battery staple");
  await user.click(screen.getByRole("button", { name: "Create account" }));
}

describe("registration transport", () => {
  it("uses the native unauthenticated registration path when the shell has no session", async () => {
    nativeShellState.value = true;
    await submitRegistration();

    await waitFor(() => expect(nativeRegister).toHaveBeenCalled());
    expect(post).not.toHaveBeenCalledWith("/auth/register", expect.anything());
    expect(push).toHaveBeenCalledWith("/verify-email");
  });

  it("keeps browser registration on the cookie transport", async () => {
    await submitRegistration();

    await waitFor(() => expect(post).toHaveBeenCalledWith("/auth/register", expect.objectContaining({
      email: "new@example.com",
      display_name: "New User",
    })));
    expect(nativeRegister).not.toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith("/verify-email");
  });
});
