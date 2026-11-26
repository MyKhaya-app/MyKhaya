"""Declarative base with no settings or engine side effects.

Alembic (migrations/env.py) imports the model metadata through this module, so
running migrations never constructs the application Settings and never needs
MYKHAYA_SECRET_KEY. mykhaya.db re-exports Base for application code.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
