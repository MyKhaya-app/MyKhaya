import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { PublicSignupState } from "@mykhaya/api-client";
import { PublicBetaOffer } from "./public-beta-offer";

const betaState: PublicSignupState = {
  signup_mode: "beta_only",
  registration_open: true,
  invitation_required: false,
  normal_signup_available: false,
  beta_joining_available: true,
  waitlist_available: false,
  joinable_count: 7,
};

describe("PublicBetaOffer", () => {
  it("uses the public backend count and beta-only registration route", () => {
    render(<PublicBetaOffer signupState={betaState} />);

    expect(screen.getByRole("heading", { name: /join mykhaya at no cost/i })).toBeInTheDocument();
    expect(screen.getByText(/complimentary ultimate access for the lifetime/i)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("7 places currently available");
    expect(screen.getByRole("link", { name: "Join the Beta" })).toHaveAttribute("href", "/founding-beta");
    expect(screen.queryByText(/free for life/i)).not.toBeInTheDocument();
  });
});
