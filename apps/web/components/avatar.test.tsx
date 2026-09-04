// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { Avatar } from "./avatar";

const nativeState = vi.hoisted(() => ({ enabled: false }));
const fetchNativeImage = vi.hoisted(() => vi.fn());

vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeState.enabled,
}));
vi.mock("./native-auth", () => ({ fetchNativeImage }));

describe("Avatar", () => {
  afterEach(() => {
    nativeState.enabled = false;
    fetchNativeImage.mockReset();
    vi.restoreAllMocks();
  });

  it("shows initials when no avatar is configured", () => {
    const { container } = render(<Avatar id="u1" name="Alice" avatarVersion={null} />);

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(container.textContent).toContain("A");
    expect(fetchNativeImage).not.toHaveBeenCalled();
  });

  it("keeps the direct protected URL on web/PWA", () => {
    const { container } = render(<Avatar id="u1" name="Alice" avatarVersion="v1" />);

    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "/api/v1/users/u1/avatar?v=v1",
    );
    expect(fetchNativeImage).not.toHaveBeenCalled();
  });

  it("loads native avatars through the authenticated blob path", async () => {
    nativeState.enabled = true;
    const createObjectURL = vi.fn().mockReturnValue("blob:avatar");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    fetchNativeImage.mockResolvedValue(new Blob(["image"], { type: "image/webp" }));
    const { container } = render(<Avatar id="u1" name="Alice" avatarVersion="v1" />);

    await waitFor(() => expect(container.querySelector("img")).toHaveAttribute("src", "blob:avatar"));
    expect(fetchNativeImage).toHaveBeenCalledWith("/users/u1/avatar?v=v1");
    expect(createObjectURL).toHaveBeenCalled();
  });

  it("shows initials when native media loading fails", async () => {
    nativeState.enabled = true;
    fetchNativeImage.mockRejectedValue(new Error("Unauthorized"));
    const { container } = render(<Avatar id="u1" name="Alice" avatarVersion="v1" />);

    await waitFor(() => expect(container.querySelector("img")).not.toBeInTheDocument());
    expect(container.textContent).toContain("A");
  });

  it("shows initials when the web image emits an error", () => {
    const { container } = render(<Avatar id="u1" name="Alice" avatarVersion="v1" />);
    const image = container.querySelector("img");
    expect(image).toBeTruthy();

    fireEvent.error(image!);

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(container.textContent).toContain("A");
  });
});
