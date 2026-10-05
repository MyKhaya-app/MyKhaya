import type { PublicSignupState } from "@mykhaya/api-client";

export type RegistrationSetting = {
  key: string;
  value: string | number | boolean | string[] | null;
};

export type RegistrationSummary = {
  signupMode: string;
  normalSignup: "Enabled" | "Disabled";
  betaSignup: "Enabled" | "Disabled";
  waitlist: "Enabled" | "Disabled";
  invitation: "Required" | "Not required";
  emailVerification: "Required" | "Optional";
  signIn: "Available";
};

const modeLabels: Record<string, string> = {
  normal: "Normal",
  beta_only: "Founding Beta only",
  mixed: "Mixed",
  closed: "Closed",
};

export function registrationSummary(
  settings: RegistrationSetting[],
  publicState: PublicSignupState | null,
): RegistrationSummary {
  const value = (key: string) => settings.find((item) => item.key === key)?.value;
  const mode = publicState?.signup_mode ?? String(value("signup_mode") ?? "normal");
  const emailRequired = value("email_verification_required") !== false;

  return {
    signupMode: modeLabels[mode] ?? mode,
    normalSignup: publicState?.normal_signup_available ? "Enabled" : "Disabled",
    betaSignup: publicState?.beta_joining_available ? "Enabled" : "Disabled",
    waitlist: publicState?.waitlist_available ? "Enabled" : "Disabled",
    invitation: publicState?.invitation_required ? "Required" : "Not required",
    emailVerification: emailRequired ? "Required" : "Optional",
    signIn: "Available",
  };
}

export function registrationSetting(settings: RegistrationSetting[], key: string) {
  return settings.find((item) => item.key === key);
}
