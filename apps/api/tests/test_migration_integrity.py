"""Static integrity checks for the Alembic revision graph."""

import ast
from pathlib import Path

MAX_ALEMBIC_VERSION_LENGTH = 32
VERSIONS_DIR = Path(__file__).parents[1] / "migrations" / "versions"


def _migration_values(path: Path) -> tuple[str, str | None]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in {"revision", "down_revision"} and node.value is not None:
                values[node.target.id] = ast.literal_eval(node.value)
    revision = values.get("revision")
    down_revision = values.get("down_revision")
    assert isinstance(revision, str), f"{path.name} must define a string revision"
    assert down_revision is None or isinstance(down_revision, str), (
        f"{path.name} must define a string or None down_revision"
    )
    return revision, down_revision


def test_alembic_revision_ids_fit_version_column_and_form_one_chain() -> None:
    migrations = sorted(VERSIONS_DIR.glob("*.py"))
    assert migrations, "No Alembic migrations discovered"
    values = [_migration_values(path) for path in migrations]
    revisions = [revision for revision, _down_revision in values]
    assert len(revisions) == len(set(revisions)), "Alembic revision IDs must be unique"
    too_long = [revision for revision in revisions if len(revision) > MAX_ALEMBIC_VERSION_LENGTH]
    assert not too_long, f"Revision IDs exceed VARCHAR(32): {too_long}"

    known = set(revisions)
    broken = [
        (path.name, down_revision)
        for path, (_revision, down_revision) in zip(migrations, values, strict=True)
        if down_revision is not None and down_revision not in known
    ]
    assert not broken, f"Broken Alembic down_revision references: {broken}"
