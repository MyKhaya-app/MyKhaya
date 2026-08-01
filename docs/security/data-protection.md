# Data Protection and Minimisation

Collect only information required for coordination. For every field document purpose, visibility, retention, deletion, export and logging behaviour.

The service must not introduce general file storage, passive location tracking, contact-book harvesting, medical records, financial records or password storage.

Prepare for account export, deletion, Home deletion, membership removal, retention limits and backup expiry. Production data must not be copied into development.

The hosted-service data inventory includes account identity/contact data, Home relationships, invitations, family coordination content, sessions/device metadata, authentication/security events, email delivery metadata, jobs, administrator records/notes/audit, public incidents and backups. Data subjects are registered users, invitees, household members and parent-managed children. Processing supports private coordination, security, service delivery, support and legal/incident handling. Storage is PostgreSQL/Redis and encrypted backups; recipients/processors may include hosting, email, monitoring and backup providers subject to contracts and transfer assessment.

The Control Centre returns operational metadata only and has no household-content browsing or impersonation API. Retention and rights workflows are documented separately and are not yet automated or complete.
