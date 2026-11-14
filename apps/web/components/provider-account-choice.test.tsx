import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PublicLegalDocumentSummary } from "@mykhaya/api-client";
import {
  identityInitials,
  maskEmail,
  ProviderAccountChoice,
  type ProviderRecoveryOptions,
} from "./provider-account-choice";

const terms: PublicLegalDocumentSummary = {
  key: "terms",
  display_name: "Terms & Conditions",
  audience: "adult",
  scope: "global",
  action_verb: "accept",
  acceptance_required: true,
  current_version: "1.0",
  current_version_id: "terms-v1",
  effective_date: null,
} as PublicLegalDocumentSummary;

const notice: PublicLegalDocumentSummary = {
  ...terms,
  key: "privacy",
  display_name: "Privacy Notice",
  action_verb: "acknowledge",
  acceptance_required: false,
  current_version_id: "privacy-v1",
} as PublicLegalDocumentSummary;

const eligible: ProviderRecoveryOptions = {
  can_register: true,
  provider_email: "anthony.hales@example.com",
  display_name: "Anthony Hales",
};

function setup(overrides: Partial<Parameters<typeof ProviderAccountChoice>[0]> = {}) {
  const props = {
    provider: "google" as const,
    idPrefix: "google",
    recovery: eligible,
    beta: false,
    legalDocuments: [terms, notice],
    legalChecked: {},
    onLegalChange: vi.fn(),
    legalLoading: false,
    legalLoadFailed: false,
    displayName: "Anthony Hales",
    onDisplayNameChange: vi.fn(),
    busy: false,
    error: "",
    linking: false,
    onChooseNew: vi.fn(),
    onChooseExisting: vi.fn(),
    onLeaveExisting: vi.fn(),
    onCreate: vi.fn(),
    onBack: vi.fn(),
    onSwitch: vi.fn(),
    signIn: <form aria-label="Existing account sign in"><input id="signin-email" aria-label="Email" /></form>,
    ...overrides,
  };
  const view = render(<ProviderAccountChoice {...props} />);
  return { props, ...view };
}

describe("ProviderAccountChoice — layout and copy", () => {
  it("shows the identity card, one question and the 'new' option selected by default", () => {
    const { props } = setup();
    expect(screen.getByRole("heading", { level: 1, name: "Welcome to MyKhaya" })).toBeInTheDocument();
    expect(screen.getByText("Is this a new account, or do you already use MyKhaya?")).toBeInTheDocument();
    expect(screen.getByText("Anthony Hales", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("Signed in with Google")).toBeInTheDocument();
    // Partly masked, and only the value the API returned.
    expect(screen.getByText("an…@example.com")).toBeInTheDocument();
    expect(screen.queryByText("anthony.hales@example.com")).not.toBeInTheDocument();
    const group = screen.getByRole("group", { name: "How would you like to continue?" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /I’m new to MyKhaya/ })).toBeChecked();
    expect(props.onChooseNew).toHaveBeenCalledTimes(1);
    // Exactly one primary action.
    expect(screen.getAllByRole("button", { name: /Create account|Continue to sign in/ })).toHaveLength(1);
    // The removed copy stays removed.
    expect(screen.queryByText(/nearly there/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/authentication successful/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Before you create your account/)).not.toBeInTheDocument();
  });

  it("labels the provider for Apple", () => {
    setup({ provider: "apple", idPrefix: "apple", recovery: { ...eligible, provider_email: "x7@privaterelay.appleid.com" } });
    expect(screen.getByText("Signed in with Apple")).toBeInTheDocument();
    expect(screen.getByText("Link Apple so you can sign in either way.")).toBeInTheDocument();
    expect(screen.getByText("x…@privaterelay.appleid.com")).toBeInTheDocument();
  });

  it("normal mode: a plain 'new' option without the Beta badge", () => {
    setup();
    expect(screen.getByText("Create your MyKhaya account")).toBeInTheDocument();
    expect(screen.queryByText("Create an account with complimentary Ultimate access")).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Sign-up progress" })).toHaveTextContent("Set up your Home");
    // Same notice confirmation as /register; no Beta Terms note outside Beta.
    expect(
      screen.getByText(/By creating an account, you confirm that these notices have been made available to you\./),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Founding Beta Terms" })).not.toBeInTheDocument();
  });

  it("Beta mode: badge, Ultimate line and the Beta final step", () => {
    setup({ beta: true });
    expect(
      screen.getByRole("radio", { name: /I’m new to MyKhaya\s*Founding Beta\s*Create an account with complimentary Ultimate access/ }),
    ).toBeChecked();
    const steps = screen.getByRole("list", { name: "Sign-up progress" });
    expect(steps).toHaveTextContent("Accept the Beta Terms and enrol your Home");
    expect(screen.getByText("Set up account").closest("li")).toHaveAttribute("aria-current", "step");
    // The provider route has no email verification: the Beta Terms come at enrolment.
    const note = screen.getByText(/You’ll review the/);
    expect(note).toHaveTextContent("You’ll review the Founding Beta Terms before your Home is enrolled.");
    expect(note).toHaveTextContent("By creating an account, you confirm that these notices have been made available to you.");
    expect(note).not.toHaveTextContent("after verifying your email");
    expect(screen.getByRole("link", { name: "Founding Beta Terms" })).toHaveAttribute("href", "/legal/founding-beta-terms");
  });

  it("falls back gracefully when the provider returned no name or email", () => {
    setup({ recovery: { can_register: true, provider_email: null, display_name: null }, displayName: "" });
    expect(screen.getByText("Your Google account")).toBeInTheDocument();
    expect(screen.getByLabelText("Your name")).toHaveValue("");
  });

  it("uses the email for the identity when only the email is known", () => {
    setup({ recovery: { can_register: true, provider_email: "sam@example.com", display_name: null } });
    expect(screen.getByText("sa…@example.com", { selector: "strong" })).toBeInTheDocument();
  });

  it("shows a loading state until the options arrive, then the choice", () => {
    const { rerender, props } = setup({ recovery: null });
    expect(screen.getByRole("status")).toHaveTextContent("Checking your Google sign-in…");
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    rerender(<ProviderAccountChoice {...props} recovery={eligible} />);
    expect(screen.getByRole("radio", { name: /I’m new to MyKhaya/ })).toBeChecked();
  });
});

describe("ProviderAccountChoice — eligibility and legal documents", () => {
  it("hides the 'new' option when registration is not allowed", () => {
    setup({ recovery: { ...eligible, can_register: false } });
    expect(screen.getByRole("heading", { level: 1, name: "Continue with Google" })).toBeInTheDocument();
    expect(screen.getByText(/New account creation is currently unavailable for this Google sign-in/)).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /I’m new to MyKhaya/ })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /I already have an account/ })).toBeChecked();
    expect(screen.getByRole("button", { name: "Continue to sign in" })).toBeEnabled();
  });

  it("renders one unticked checkbox per required document, with its version and link", () => {
    setup();
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(1);
    expect(boxes[0]).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "I agree to the Terms & Conditions (v1.0)." })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Terms & Conditions" })).toHaveAttribute("href", "/legal/terms");
    expect(screen.getByRole("link", { name: "Privacy Notice" })).toHaveAttribute("href", "/legal/privacy");
  });

  it("keeps Create account disabled until every required document is accepted", async () => {
    const { rerender, props } = setup();
    const create = screen.getByRole("button", { name: "Create account" });
    expect(create).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox"));
    expect(props.onLegalChange).toHaveBeenCalledWith("terms", true);
    rerender(<ProviderAccountChoice {...props} legalChecked={{ terms: true }} />);
    expect(screen.getByRole("button", { name: "Create account" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(props.onCreate).toHaveBeenCalledTimes(1);
  });

  it("does not allow creation while the legal documents load or after they fail", () => {
    const { rerender, props } = setup({ legalLoading: true, legalChecked: { terms: true } });
    expect(screen.getByText("Loading the current legal documents…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeDisabled();
    rerender(<ProviderAccountChoice {...props} legalLoading={false} legalLoadFailed />);
    expect(screen.getByText(/could not be loaded/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeDisabled();
  });

  it("announces errors through FormStatus", () => {
    setup({ error: "Please enter your name before continuing." });
    expect(screen.getByText("Please enter your name before continuing.")).toBeInTheDocument();
  });
});

describe("ProviderAccountChoice — link path, back and switch", () => {
  it("reveals the explanation, then the existing sign-in only after Continue to sign in", async () => {
    const user = userEvent.setup();
    const { rerender, props } = setup();
    await user.click(screen.getByRole("radio", { name: /I already have an account/ }));
    expect(screen.getByText(/Google will be linked only after that authentication succeeds/)).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Existing account sign in" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue to sign in" }));
    expect(props.onChooseExisting).toHaveBeenCalledTimes(1);

    rerender(<ProviderAccountChoice {...props} linking />);
    expect(screen.getByRole("form", { name: "Existing account sign in" })).toBeInTheDocument();
    // Focus moves to the email field that just appeared.
    expect(screen.getByLabelText("Email")).toHaveFocus();
    // The sign-in form's own button is now the only primary action.
    expect(screen.queryByRole("button", { name: /Create account|Continue to sign in/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /I’m new to MyKhaya/ }));
    expect(props.onLeaveExisting).toHaveBeenCalledTimes(1);
  });

  it("moves focus to the name field when 'new' is chosen again", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("radio", { name: /I already have an account/ }));
    await user.click(screen.getByRole("radio", { name: /I’m new to MyKhaya/ }));
    expect(screen.getByLabelText("Your name")).toHaveFocus();
  });

  it("Back cancels and Switch restarts the provider", async () => {
    const user = userEvent.setup();
    const { props } = setup({ provider: "apple", idPrefix: "native" });
    await user.click(screen.getByRole("button", { name: "Back to sign in" }));
    expect(props.onBack).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Switch Apple account" }));
    expect(props.onSwitch).toHaveBeenCalledTimes(1);
  });

  it("disables every action while a request is in flight", () => {
    setup({ busy: true, legalChecked: { terms: true } });
    expect(screen.getByRole("button", { name: "Creating account…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Back to sign in" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /I already have an account/ })).toBeDisabled();
  });
});

describe("identity helpers", () => {
  it("masks only the local part", () => {
    expect(maskEmail("anthony@example.com")).toBe("an…@example.com");
    expect(maskEmail("ab@example.com")).toBe("a…@example.com");
    expect(maskEmail("not-an-email")).toBe("not-an-email");
  });

  it("derives initials from the name, then the email", () => {
    expect(identityInitials("Anthony Hales", null)).toBe("AH");
    expect(identityInitials("  Thandi  ", null)).toBe("T");
    expect(identityInitials(null, "sam@example.com")).toBe("S");
    expect(identityInitials(null, null)).toBe("");
  });
});
