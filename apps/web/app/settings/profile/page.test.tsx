import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
      updateMyBirthday: vi.fn(),
    },
  };
});
const { api, ApiError } = await import("@mykhaya/api-client");

// isNativeShell is the single switch between the two avatar-selection paths
// (ADR 0013) — false by default so the existing HTML-input suite above
// keeps testing the web/PWA path unchanged; the native describe block below
// sets it true per test.
let nativeShell = false;
vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => nativeShell,
  nativePlatform: () => (nativeShell ? "ios" : "web"),
}));

// Avatar (rendered by this page) independently branches on isNativeShell()
// to fetch the *displayed* avatar image via a bearer-authenticated native
// request — unrelated to this file's concern (native *selection* of a new
// photo), but exercised as a side effect of nativeShell=true above. Mocked
// out so it fails softly (Avatar's own .catch() falls back to initials)
// instead of throwing "No native API origin configured for web host" in a
// jsdom test that has no real native session.
vi.mock("@/components/native-auth", () => ({
  fetchNativeImage: vi.fn().mockRejectedValue(new Error("not available in tests")),
}));

vi.mock("@/components/native-avatar-picker", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/native-avatar-picker")>();
  return {
    ...actual,
    pickAvatarFromCamera: vi.fn(),
    pickAvatarFromGallery: vi.fn(),
  };
});
const { NativeAvatarPickerError, pickAvatarFromCamera, pickAvatarFromGallery } = await import(
  "@/components/native-avatar-picker"
);

const BASE_USER = {
  id: "u1",
  display_name: "Megan",
  email: "megan@example.com",
  email_verified: true,
  principal_type: "adult" as const,
  avatar_version: null as string | null,
  birth_month: null,
  birth_day: null,
  birth_year: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  nativeShell = false;
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
  it("uses accept=\"image/*\" for the Photos-library picker, never an enumerated MIME list", async () => {
    // WKWebView's Photos-library transcoding is sensitive to which image
    // MIME types accept declares — explicitly listing image/heic,image/heif
    // has been observed to change whether iOS hands back a transcoded JPEG
    // or the original bytes. "Any image" is the only value that takes no
    // position on that; the backend decodes/validates the real bytes.
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    expect(fileInputs(container).library).toHaveAttribute("accept", "image/*");
  });

  it("uses accept=\"image/*\" with capture=\"environment\" for the camera input", async () => {
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    const { camera } = fileInputs(container);
    expect(camera).toHaveAttribute("accept", "image/*");
    expect(camera).toHaveAttribute("capture", "environment");
  });

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

// Account details is a compact profile summary, not a form: Month/Day
// controls and Save/Cancel are only ever present while explicitly editing
// the birthday, never shown by default.
describe("Profile — Account details summary", () => {
  it("shows Name, Email with verified status, Home role and Birthday as plain read-only rows, with no Save/Cancel visible", async () => {
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      birth_month: 2,
      birth_day: 6,
    });
    render(<Profile />);
    const heading = await screen.findByRole("heading", { name: "Account details" });
    const card = heading.closest("section")!;

    expect(within(card).getByText("Megan", { selector: "dd" })).toBeInTheDocument();
    expect(within(card).getByText("megan@example.com")).toBeInTheDocument();
    expect(within(card).getByText("Verified")).toBeInTheDocument();
    // "Home admin" also appears in the identity pill above this card — wait
    // for it inside this card specifically, once membership has loaded.
    expect(await within(card).findByText("Home admin")).toBeInTheDocument();
    // "6 February" — day first, full month name.
    expect(within(card).getByText("6 February")).toBeInTheDocument();
    expect(
      within(card).getByText("Shared with your household so they can wish you well."),
    ).toBeInTheDocument();

    expect(within(card).queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(card).queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("shows 'Verification needed' when the email is not yet verified", async () => {
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ ...BASE_USER, email_verified: false });
    render(<Profile />);
    await screen.findByRole("heading", { name: "Account details" });
    expect(screen.getByText("Verification needed")).toBeInTheDocument();
    expect(screen.queryByText("Verified")).not.toBeInTheDocument();
  });

  it("shows 'Not set' for a birthday that has never been saved", async () => {
    render(<Profile />);
    await screen.findByRole("heading", { name: "Account details" });
    expect(screen.getByText("Not set")).toBeInTheDocument();
  });

  it("reveals the Month/Day editing controls and Save/Cancel only after Edit is selected", async () => {
    render(<Profile />);
    await screen.findByRole("heading", { name: "Account details" });
    await waitFor(() => expect(screen.getAllByText("Home admin").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(screen.getByRole("combobox", { name: "Month" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Day" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("Cancel hides the editing controls again without saving", async () => {
    render(<Profile />);
    await screen.findByRole("heading", { name: "Account details" });
    await waitFor(() => expect(screen.getAllByText("Home admin").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("combobox", { name: "Month" })).not.toBeInTheDocument();
    expect(api.updateMyBirthday).not.toHaveBeenCalled();
  });

  it("Save updates the birthday and collapses back to the summary view", async () => {
    (api.updateMyBirthday as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      birth_month: 2,
      birth_day: 6,
    });
    render(<Profile />);
    await screen.findByRole("heading", { name: "Account details" });

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Month" }), { target: { value: "2" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Day" }), { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api.updateMyBirthday).toHaveBeenCalledWith({ birth_month: 2, birth_day: 6 }),
    );
    expect(await screen.findByText("6 February")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Month" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });
});

// Native iOS avatar selection (ADR 0013): inside the Capacitor shell, the
// bottom sheet's Take photo/Choose from library actions must use the
// Capacitor Camera plugin, never the hidden HTML file input — the
// unreliable WKWebView Photos-library picker this replaces. isNativeShell
// and the picker functions are both mocked (see top of file); the plugin's
// own behaviour is covered separately in native-avatar-picker.test.ts.
describe("Profile — native iOS avatar selection", () => {
  function nativeFile(name = "photos-123.jpg") {
    return new File([new Uint8Array(1024)], name, { type: "image/jpeg" });
  }

  async function openPhotoSheet() {
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    fireEvent.click(screen.getByRole("button", { name: /change photo/i }));
    return container;
  }

  it("Choose from library uses the Capacitor Camera plugin, not the HTML file input", async () => {
    nativeShell = true;
    (pickAvatarFromGallery as ReturnType<typeof vi.fn>).mockResolvedValue(nativeFile());
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "native.webp",
    });
    await openPhotoSheet();

    fireEvent.click(screen.getByRole("button", { name: "Choose from library" }));

    await waitFor(() => expect(pickAvatarFromGallery).toHaveBeenCalledTimes(1));
    expect(pickAvatarFromCamera).not.toHaveBeenCalled();
  });

  it("Take photo uses the Capacitor Camera plugin, not the HTML file input", async () => {
    nativeShell = true;
    (pickAvatarFromCamera as ReturnType<typeof vi.fn>).mockResolvedValue(nativeFile("camera-123.jpg"));
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "native.webp",
    });
    await openPhotoSheet();

    fireEvent.click(screen.getByRole("button", { name: /take photo/i }));

    await waitFor(() => expect(pickAvatarFromCamera).toHaveBeenCalledTimes(1));
    expect(pickAvatarFromGallery).not.toHaveBeenCalled();
  });

  it("does not render the hidden HTML file inputs at all inside the native shell", async () => {
    nativeShell = true;
    const { container } = render(<Profile />);
    await screen.findByRole("heading", { name: "Megan" });
    expect(container.querySelectorAll('input[type="file"]')).toHaveLength(0);
  });

  it("web/PWA (isNativeShell false) still uses the HTML file input, unaffected", async () => {
    nativeShell = false;
    const container = await openPhotoSheet();
    fireEvent.click(screen.getByRole("button", { name: "Choose from library" }));

    expect(pickAvatarFromGallery).not.toHaveBeenCalled();
    expect(container.querySelectorAll('input[type="file"]')).toHaveLength(2);
  });

  it("picker cancellation (picker resolves null) produces no error message", async () => {
    nativeShell = true;
    (pickAvatarFromGallery as ReturnType<typeof vi.fn>).mockResolvedValue(null);
    await openPhotoSheet();

    fireEvent.click(screen.getByRole("button", { name: "Choose from library" }));

    await waitFor(() => expect(pickAvatarFromGallery).toHaveBeenCalled());
    expect(api.uploadAvatar).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("permission denial shows the MyKhaya-worded permission message, not a raw native error", async () => {
    nativeShell = true;
    (pickAvatarFromGallery as ReturnType<typeof vi.fn>).mockRejectedValue(
      new NativeAvatarPickerError(
        "permission",
        "MyKhaya doesn’t have permission to access your photos. You can allow access in iPhone Settings.",
      ),
    );
    await openPhotoSheet();

    fireEvent.click(screen.getByRole("button", { name: "Choose from library" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "MyKhaya doesn’t have permission to access your photos. You can allow access in iPhone Settings.",
    );
  });

  it("a picker read failure shows the 'couldn't read that photo' message", async () => {
    nativeShell = true;
    (pickAvatarFromCamera as ReturnType<typeof vi.fn>).mockRejectedValue(
      new NativeAvatarPickerError("read", "We couldn’t read that photo. Please try another image."),
    );
    await openPhotoSheet();

    fireEvent.click(screen.getByRole("button", { name: /take photo/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We couldn’t read that photo. Please try another image.",
    );
  });

  it("the native asset becomes a valid File and reaches api.uploadAvatar", async () => {
    nativeShell = true;
    const file = nativeFile();
    (pickAvatarFromGallery as ReturnType<typeof vi.fn>).mockResolvedValue(file);
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "native.webp",
    });
    await openPhotoSheet();

    fireEvent.click(screen.getByRole("button", { name: "Choose from library" }));

    await waitFor(() => expect(api.uploadAvatar).toHaveBeenCalledWith(file));
  });

  it("a large native phone photo is not rejected client-side", async () => {
    nativeShell = true;
    const file = new File([new Uint8Array(9_000_000)], "photos-large.jpg", { type: "image/jpeg" });
    (pickAvatarFromGallery as ReturnType<typeof vi.fn>).mockResolvedValue(file);
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "native.webp",
    });
    await openPhotoSheet();

    fireEvent.click(screen.getByRole("button", { name: "Choose from library" }));

    await waitFor(() => expect(api.uploadAvatar).toHaveBeenCalledWith(file));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("a successful native upload updates avatar state and broadcasts the header refresh", async () => {
    nativeShell = true;
    (pickAvatarFromGallery as ReturnType<typeof vi.fn>).mockResolvedValue(nativeFile());
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "native-broadcast.webp",
    });
    const received: string[] = [];
    function Listener() {
      useUserUpdatedListener((user) => received.push(user.avatar_version ?? ""));
      return null;
    }
    render(
      <>
        <Listener />
        <Profile />
      </>,
    );
    await screen.findByRole("heading", { name: "Megan" });
    fireEvent.click(screen.getByRole("button", { name: /change photo/i }));
    fireEvent.click(screen.getByRole("button", { name: "Choose from library" }));

    expect(await screen.findByText("Your photo was updated.")).toBeInTheDocument();
    await waitFor(() => expect(received).toEqual(["native-broadcast.webp"]));
  });

  it("a failed native upload preserves the existing avatar (backend error mapping still applies)", async () => {
    nativeShell = true;
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BASE_USER,
      avatar_version: "existing.webp",
    });
    (pickAvatarFromGallery as ReturnType<typeof vi.fn>).mockResolvedValue(nativeFile());
    (api.uploadAvatar as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(422, "That image format is not supported. Please upload a JPEG, PNG or WebP photo."),
    );
    const received: string[] = [];
    function Listener() {
      useUserUpdatedListener((user) => received.push(user.avatar_version ?? ""));
      return null;
    }
    render(
      <>
        <Listener />
        <Profile />
      </>,
    );
    await screen.findByRole("heading", { name: "Megan" });
    fireEvent.click(screen.getByRole("button", { name: /change photo/i }));
    fireEvent.click(screen.getByRole("button", { name: "Choose from library" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This photo format isn’t supported. Please choose another photo.",
    );
    // Same backend-error-mapping path as the web suite above — the
    // selection mechanism changed, the backend contract and its error
    // mapping did not.
    expect(received).toEqual([]);
  });
});
