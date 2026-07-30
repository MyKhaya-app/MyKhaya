# Backend Standards

- Use FastAPI, Pydantic, SQLAlchemy 2 and Alembic.
- Keep routes thin; business rules belong in services.
- Use explicit repositories scoped to an authorised Home.
- Never expose unrestricted database models as request bodies.
- Use versioned APIs under `/api/v1`.
- Use structured errors, request IDs and timezone-aware UTC timestamps.
- Bound pagination, date ranges, recurrence and resource use.
- Use transactions for related writes and a transactional outbox for important downstream events.
- All reusable authentication and invitation secrets are stored as hashes.
- Do not leak stack traces, SQL errors or configuration.
