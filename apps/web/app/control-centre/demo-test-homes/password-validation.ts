// Shared password validation for managed Demo/Test Home accounts — used by
// both the create form (demo-test-homes/page.tsx) and the reset-password
// dialog (demo-test-homes/[id]/page.tsx), which previously duplicated the
// same length/match check independently. Mirrors the backend's
// ManagedDemoHomeCreate/ManagedDemoPasswordReset `password` field
// (min_length=12) in apps/api/mykhaya/platform_schemas.py — kept in sync
// with that, not an independent policy.
export const MANAGED_DEMO_PASSWORD_MIN_LENGTH = 12;

export function validateManagedDemoPassword(password: string, confirmPassword: string): string | null {
  if (password.length < MANAGED_DEMO_PASSWORD_MIN_LENGTH || password !== confirmPassword) {
    return `Passwords must match and be at least ${MANAGED_DEMO_PASSWORD_MIN_LENGTH} characters.`;
  }
  return null;
}
