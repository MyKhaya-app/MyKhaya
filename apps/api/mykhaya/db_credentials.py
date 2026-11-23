"""Database connection credentials (MK-SEC-001 v1.2 SEC-086, SEC-086a).

Two ways to supply the database password:

* **Legacy** (every current deployment): the password is embedded in
  ``MYKHAYA_DATABASE_URL``. Nothing about that form changes here.
* **File-backed**: ``MYKHAYA_DATABASE_URL`` carries no password and
  ``MYKHAYA_DATABASE_PASSWORD_FILE`` names the file (read through the central
  secret registry). The password is attached to SQLAlchemy's structured
  ``URL`` object inside the process, so it never has to be percent-encoded,
  is never written back into a URL string or an environment variable, and is
  never part of a diagnostic.

The application (``Settings``) and the migrator (``MigrationSettings``) each
resolve their own URL and password, so the application identity
(``mykhaya_app``, K-02) and the migration identity (``mykhaya_migrator``,
K-03) stay separate; mykhaya.process_roles enforces which user each role uses.

Every error names settings only. SQLAlchemy's own parse error is never
propagated because it quotes the URL, password included.
"""

from pydantic import SecretStr
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

UNPARSEABLE = "<unparseable database URL>"


def _parse(database_url: str) -> URL | None:
    try:
        return make_url(database_url)
    except (ArgumentError, ValueError, TypeError):
        return None


def database_credential_problems(database_url: str, password: SecretStr | None) -> list[str]:
    """Checks that apply only in file-backed mode (a password was loaded from
    MYKHAYA_DATABASE_PASSWORD_FILE). The legacy URL form is not re-validated,
    so existing deployments behave exactly as before."""
    if password is None:
        return []
    url = _parse(database_url)
    if url is None:
        return ["MYKHAYA_DATABASE_URL is not a valid database URL"]
    problems: list[str] = []
    if url.password is not None:
        problems.append(
            "MYKHAYA_DATABASE_URL must not contain a password when "
            "MYKHAYA_DATABASE_PASSWORD_FILE is set"
        )
    if not url.username:
        problems.append(
            "MYKHAYA_DATABASE_URL must name a database user when "
            "MYKHAYA_DATABASE_PASSWORD_FILE is set"
        )
    return problems


def connection_url(database_url: str, password: SecretStr | None) -> URL:
    """The URL object to connect with. In file-backed mode the password is
    attached as a structured field; in legacy mode the URL is used as given.
    A malformed URL raises an error that never quotes it (SQLAlchemy's own
    error, previously raised at engine creation, includes the password)."""
    url = _parse(database_url)
    if url is None:
        raise ValueError("MYKHAYA_DATABASE_URL is not a valid database URL")
    if password is None:
        return url
    return url.set(password=password.get_secret_value())


def redacted_database_url(database_url: str) -> str:
    """A diagnostic form of the URL with any password masked."""
    url = _parse(database_url)
    if url is None:
        return UNPARSEABLE
    return url.render_as_string(hide_password=True)


def has_database_password(database_url: str, password: SecretStr | None) -> bool:
    """Whether this configuration supplies a database password by either form."""
    if password is not None and password.get_secret_value():
        return True
    url = _parse(database_url)
    return bool(url is not None and url.password)
