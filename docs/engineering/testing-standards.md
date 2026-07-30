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

A scanner passing does not replace manual security review.
