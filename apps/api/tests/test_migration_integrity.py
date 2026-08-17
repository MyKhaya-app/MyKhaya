"""Static integrity checks for the Alembic revision graph.

Regression coverage for the 0029_home_calendar_colour incident: a file was
renamed/renumbered mid-development without realising its revision ID had
already been deployed, orphaning any database stamped at the old ID
("Can't locate revision identified by '0029_home_calendar_colour'"). These
checks catch that class of mistake — a broken down_revision reference, or
an unexpected extra head — before it reaches a deployment.
"""

import ast
from pathlib import Path

MAX_ALEMBIC_VERSION_LENGTH = 32
VERSIONS_DIR = Path(__file__).parents[1] / "migrations" / "versions"
# Bump this only for a deliberate, reviewed branch (e.g. mid-merge of two
# concurrent feature branches) — see docs/operations/dev-deployment.md.
EXPECTED_HEAD_COUNT = 1


def _migration_values(path: Path) -> tuple[str, str | tuple[str, ...] | None]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in {"revision", "down_revision"} and node.value is not None:
                values[node.target.id] = ast.literal_eval(node.value)
    revision = values.get("revision")
    down_revision = values.get("down_revision")
    assert isinstance(revision, str), f"{path.name} must define a string revision"
    # A merge migration's down_revision is a tuple of every branch it joins.
    is_str_tuple = isinstance(down_revision, tuple) and all(
        isinstance(item, str) for item in down_revision
    )
    assert down_revision is None or isinstance(down_revision, str) or is_str_tuple, (
        f"{path.name} must define a string, tuple of strings, or None down_revision"
    )
    return revision, down_revision


def _down_revisions(down_revision: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if down_revision is None:
        return ()
    if isinstance(down_revision, tuple):
        return down_revision
    return (down_revision,)


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
        (path.name, target)
        for path, (_revision, down_revision) in zip(migrations, values, strict=True)
        for target in _down_revisions(down_revision)
        if target not in known
    ]
    assert not broken, (
        f"Broken Alembic down_revision references (a revision ID a migration "
        f"depends on no longer exists as a file — restore or repoint it, "
        f"never delete a revision ID that may already be deployed): {broken}"
    )


def test_alembic_graph_has_exactly_one_head() -> None:
    """A second, unmerged head means some database can walk forward from
    base and land somewhere `alembic upgrade head` on another database
    would never reach — exactly how 0029_home_calendar_colour and
    0029_trusted_devices silently diverged from 0028_personal_calendars
    until a merge migration reconnected them."""
    migrations = sorted(VERSIONS_DIR.glob("*.py"))
    values = [_migration_values(path) for path in migrations]
    revisions = {revision for revision, _down_revision in values}

    referenced_as_parent: set[str] = set()
    for _revision, down_revision in values:
        referenced_as_parent.update(_down_revisions(down_revision))

    heads = sorted(revisions - referenced_as_parent)
    assert len(heads) == EXPECTED_HEAD_COUNT, (
        f"Expected {EXPECTED_HEAD_COUNT} Alembic head(s), found {len(heads)}: {heads}. "
        "If this is a genuine concurrent-branch situation, add an Alembic merge "
        "migration to reconnect them (see 0030_home_calendar_colour for the pattern) "
        "rather than raising EXPECTED_HEAD_COUNT."
    )


def test_alembic_chain_resolves_from_base_to_every_head() -> None:
    """Every revision must be reachable from base by following down_revision
    links forward — i.e. the graph is fully connected, not just internally
    consistent. Catches a revision that references a real, existing
    down_revision but is itself unreachable (e.g. two disconnected chains
    that both happen to start at a valid but different root)."""
    migrations = sorted(VERSIONS_DIR.glob("*.py"))
    values = [_migration_values(path) for path in migrations]
    revisions = {revision for revision, _down_revision in values}

    children_of: dict[str | None, list[str]] = {}
    for revision, down_revision in values:
        for parent in _down_revisions(down_revision) or (None,):
            children_of.setdefault(parent, []).append(revision)

    reachable: set[str] = set()
    frontier = list(children_of.get(None, []))
    while frontier:
        revision = frontier.pop()
        if revision in reachable:
            continue
        reachable.add(revision)
        frontier.extend(children_of.get(revision, []))

    unreachable = sorted(revisions - reachable)
    assert not unreachable, (
        f"Revisions unreachable from base by following down_revision forward: "
        f"{unreachable} — the graph is not fully connected."
    )
