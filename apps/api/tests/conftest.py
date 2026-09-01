"""Safe defaults required while importing the API test application."""

import os  # noqa: I001


# Tests must never depend on a production secret or a developer's .env file.
# This value only satisfies Settings validation; it is not used outside tests.
os.environ.setdefault(
    "MYKHAYA_SECRET_KEY", "test-only-secret-key-never-used-in-production-1234"
)
os.environ.setdefault(
    "MYKHAYA_TRUSTED_HOSTS",
    '["localhost", "127.0.0.1", "api", "api.localhost", "admin.localhost", "status.localhost"]',
)
os.environ.setdefault(
    "MYKHAYA_CORS_ORIGINS",
    '["http://localhost:8080", "http://admin.localhost:8080"]',
)
