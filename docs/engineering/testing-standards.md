# Testing Standards

Testing must cover behaviour, security and operations.

## Required layers

- Backend unit and integration tests
- Web component and route tests
- Mobile checks
- Playwright end-to-end journeys
- Migration tests
- Worker and scheduler tests
- Security-focused tests

## Mandatory security cases

- Cross-Home ID substitution
- Role escalation
- Removed-member access
- Invitation, reset and session-token replay
- Anonymous protected access
- Mass assignment
- CSRF and CORS behaviour
- Open redirect attempts
- XSS and injection payload handling
- Resource and pagination limits
- Safe error disclosure
- Session lifecycle across transports: a token must not be extended, renewed or
  converted into the other transport's credential in a way that skips the
  current authentication policy (see
  [Consumer MFA enforcement](consumer-mfa-enforcement.md#session-lifecycle-and-rotation-web-and-native))

A scanner passing does not replace manual security review. Scanner triage,
synthetic fixture conventions, container health checks and the full
release-candidate validation procedure are in
[CI security scanning and validation](ci-security-scanning.md).

## Deterministic tests

A test must give the same result on any machine and any date:

- Pin the clock (`vi.useFakeTimers({ toFake: ["Date"] })` with
  `vi.setSystemTime`) whenever fixtures use fixed calendar dates. Otherwise the
  test starts failing once the real date leaves the fixture's month.
- Normalise line endings when a test parses a source file
  (`.replace(/\r\n/g, "\n")`). Windows checkouts with `core.autocrlf` have
  CRLF, so `"\n}\n"`-style slicing silently reads the wrong text.
- Override settings for provider-dependent assertions (push, email, billing,
  sign-in providers). The API test stack loads the repository `.env`, so a
  developer's real configuration must not change a test's outcome.
- Use unique identifiers (for example a provider subject per test run) rather
  than fixed literals, so a rerun against the same database still tests the
  intended case.
