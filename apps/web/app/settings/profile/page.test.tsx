import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Profile from "./page";
import { useUserUpdatedListener } from "@/components/user-events";

// Coverage for the profile-photo upload flow — see the iPhone Photos-library
// HEIC investigation this file resulted from. The client never decodes or
// rejects by format/size; it only classifies the backend's real response
// into one of the established error categories (avatar-upload.ts) and
// otherwise passes the selected File straight through.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings/profile",
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: { id: "home-1", name: "Hales Home" },
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      members: vi.fn(),
      uploadAvatar: vi.fn(),
      removeAvatar: vi.fn(),
      updateMemberColour: vi.fn(),
    },
  };
});
const { api, ApiError } = await import("@mykhaya/api-client");

const BASE_USER = {
  id: "u1",
  display_name: "Megan",
  email: "megan@example.com",
  principal_type: "adult" as const,
  avatar_version: null as string | null,
  birth_month: null,
  birth_day: null,
  birth_year: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ ...BASE_USER });
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
    { user_id: "u1", relationship: "home_admin", colour: "sage" },
  ]);
});

function fileInputs(container: HTMLElement) {
  const inputs = container.querySelectorAll<HTMLInputElement>('input[type="file"]');
  const [library, camera] = inputs;
  if (!library || !camera) throw new Error("Expected both file inputs to be present.");
  return { library, camera };
}

function heicFile(sizeBytes = 2_000_000) {
  return new File([new Uint8Array(sizeBytes)], "IMG_4821.HEIC", { type: "image/heic" });
}

function largePhoneJpeg() {
  // A genuine, legitimate modern-iPhone-sized photo — well over the retired
  // 5 MB client-side ceiling, and still under the API's 20 MiB one.
  return new File([new Uint8Array(9_000_000)], "IMG_9001.JPG", { type: "image/jpeg" });
}

async function selectFile(container: HTMLElement, input: HTMLInputElement, file: File) {
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

describe("Profile — avatar upload", () => {
  it("1. a Photos-library HEIC file is sent to the API unchanged, not rejected client-side", async () => {
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "new-version.webp",
    });
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    const { library } = fileInputs(container);
    const file = heicFile();
    await selectFile(container, library, file);

    await waitFor(() => expect(api.uploadAvatar).toHaveBeenCalledWith(file));
  });

  it("2. a large legitimate phone photo (> retired 5 MB ceiling) is not rejected client-side", async () => {
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "new-version.webp",
    });
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    const { library } = fileInputs(container);
    const file = largePhoneJpeg();
    await selectFile(container, library, file);

    await waitFor(() => expect(api.uploadAvatar).toHaveBeenCalledWith(file));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("3. a camera JPEG capture still works", async () => {
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "new-version.webp",
    });
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    const { camera } = fileInputs(container);
    const file = new File([new Uint8Array(500_000)], "selfie.jpg", { type: "image/jpeg" });
    await selectFile(container, camera, file);

    await waitFor(() => expect(api.uploadAvatar).toHaveBeenCalledWith(file));
    expect(await screen.findByText("Your photo was updated.")).toBeInTheDocument();
  });

  it("4. a backend unsupported-format response maps to the unsupported-format message", async () => {
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(422, "That image format is not supported. Please upload a JPEG, PNG or WebP photo."),
    );
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    await selectFile(container, fileInputs(container).library, heicFile());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This photo format isn’t supported. Please choose another photo.",
    );
  });

  it("5. a backend unreadable/corrupt response maps to the read-failure message", async () => {
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(422, "That file could not be read as an image. Please upload a JPEG, PNG or WebP photo."),
    );
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    await selectFile(container, fileInputs(container).library, heicFile());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We couldn’t read that photo from your device. Please try selecting it again.",
    );
  });

  it("6. a backend resource-limit (413) response maps to the size/process message", async () => {
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(413, "That photo is too large to process. Please choose another image."),
    );
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    await selectFile(container, fileInputs(container).library, largePhoneJpeg());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That photo is too large to process. Please choose another image.",
    );
  });

  it("7. a network failure (no ApiError) shows the network-failure message", async () => {
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockRejectedValue(new TypeError("Failed to fetch"));
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    await selectFile(container, fileInputs(container).library, heicFile());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We couldn’t upload your photo. Please check your connection and try again.",
    );
  });

  it("8. a server failure (5xx) shows the server-failure message", async () => {
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(500, "Internal server error"),
    );
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    await selectFile(container, fileInputs(container).library, heicFile());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your photo couldn’t be saved right now. Please try again shortly.",
    );
  });

  it("9. a successful retry clears the previous error", async () => {
    (api.uploadAvatar as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(
        new ApiError(422, "That image format is not supported. Please upload a JPEG, PNG or WebP photo."),
      )
      .mockResolvedValueOnce({ ...BASE_USER, avatar_version: "recovered.webp" });
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    const { library } = fileInputs(container);

    await selectFile(container, library, heicFile());
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    await selectFile(container, library, heicFile());
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(await screen.findByText("Your photo was updated.")).toBeInTheDocument();
  });

  it("10. a failed replacement preserves the current avatar (no state change on failure)", async () => {
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "existing.webp",
    });
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(422, "That image format is not supported. Please upload a JPEG, PNG or WebP photo."),
    );
    const received: string[] = [];
    function Listener() {
      useUserUpdatedListener((user) => received.push(user.avatar_version ?? ""));
      return null;
    }
    const { container } = render(
      <>
        <Listener />
        <Profile />
      </>,
    );
    await screen.findByRole("heading", { name: "Megan" });
    await selectFile(container, fileInputs(container).library, heicFile());

    await screen.findByRole("alert");
    // The global avatar-refresh broadcast only ever fires from a successful
    // upload's own setUser/emitUserUpdated call (see test 12) — a failure
    // must never reach it, so the existing avatar reference is untouched.
    expect(received).toEqual([]);
  });

  it("11. a successful upload updates the avatar_version in page state", async () => {
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "brand-new.webp",
    });
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    await selectFile(container, fileInputs(container).library, heicFile());

    expect(await screen.findByText("Your photo was updated.")).toBeInTheDocument();
    // The "Remove photo" action only ever renders once avatar_version is set.
    expect(await screen.findByRole("button", { name: /remove photo/i })).toBeInTheDocument();
  });

  it("12. a successful upload broadcasts the global/header avatar-refresh event", async () => {
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "broadcast-me.webp",
    });
    const received: string[] = [];
    function Listener() {
      useUserUpdatedListener((user) => received.push(user.avatar_version ?? ""));
      return null;
    }
    const { container } = render(
      <>
        <Listener />
        <Profile />
      </>,
    );
    await screen.findByRole("heading", { name: "Megan" });
    await selectFile(container, fileInputs(container).library, heicFile());

    await waitFor(() => expect(received).toEqual(["broadcast-me.webp"]));
  });
});
