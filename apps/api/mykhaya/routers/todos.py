from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.entitlements import require_entitlement
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, require_capability
from mykhaya.models import (
    FeatureKey,
    Membership,
    RoutineScope,
    Todo,
    TodoCategory,
    TodoMember,
)
from mykhaya.notifications.visibility import active_membership
from mykhaya.schemas import (
    TodoCategoryCreate,
    TodoCategoryListResponse,
    TodoCategoryResponse,
    TodoCategoryUpdate,
    TodoCompletionRequest,
    TodoCreate,
    TodoListResponse,
    TodoResponse,
    TodoUpdate,
)

router = APIRouter(prefix="/homes", tags=["nudges"])


async def _require_member(home_id: uuid.UUID, auth: AuthContext, db: AsyncSession) -> Membership:
    membership = await active_membership(db, home_id, auth.user.id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    # Access to Nudges data/functionality — distinct from whether a
    # particular notification can actually be sent (Notifications is core
    # platform infrastructure, not a Home module, and must never gate
    # whether a To-do can be created/edited/completed).
    #
    # Module/platform gate first, then commercial entitlement (Phase 2B) —
    # Nudges is Family-only, independently of any Home FeatureOverride.
    await require_feature(db, FeatureKey.nudges, home_id)
    await require_entitlement(db, home_id, "nudges.enabled")
    return membership


async def _member_ids(db: AsyncSession, todo_id: uuid.UUID) -> list[uuid.UUID]:
    return sorted(
        (
            await db.scalars(select(TodoMember.user_id).where(TodoMember.todo_id == todo_id))
        ).all()
    )


def _visible(todo: Todo, user_id: uuid.UUID) -> bool:
    return todo.scope == RoutineScope.household or todo.owner_user_id == user_id


async def _category_response(row: TodoCategory) -> TodoCategoryResponse:
    return TodoCategoryResponse(
        id=row.id,
        name=row.name,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _response(db: AsyncSession, todo: Todo) -> TodoResponse:
    category = await db.get(TodoCategory, todo.category_id) if todo.category_id else None
    return TodoResponse(
        id=todo.id,
        title=todo.title,
        description=todo.description,
        scope=todo.scope,
        owner_user_id=todo.owner_user_id,
        category=await _category_response(category) if category else None,
        due_date=todo.due_date,
        completed_at=todo.completed_at,
        completed_by=todo.completed_by,
        member_ids=await _member_ids(db, todo.id),
        overdue=todo.completed_at is None and todo.due_date < datetime.now(UTC).date(),
        created_by=todo.created_by,
        updated_at=todo.updated_at,
    )


async def _validate_members(
    db: AsyncSession, home_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    requested = sorted(set(member_ids))
    if not requested:
        return requested
    found = set(
        (
            await db.scalars(
                select(Membership.user_id).where(
                    Membership.group_id == home_id,
                    Membership.removed_at.is_(None),
                    Membership.user_id.in_(requested),
                )
            )
        ).all()
    )
    if found != set(requested):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A selected member is invalid")
    return requested


async def _category_for_home(
    db: AsyncSession, home_id: uuid.UUID, category_id: uuid.UUID | None
) -> TodoCategory | None:
    if category_id is None:
        return None
    row = await db.scalar(
        select(TodoCategory).where(TodoCategory.id == category_id, TodoCategory.group_id == home_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That To-do category is invalid")
    return row


@router.get("/{home_id}/todo-categories", response_model=TodoCategoryListResponse)
async def list_categories(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> TodoCategoryListResponse:
    await _require_member(home_id, auth, db)
    rows = (
        await db.scalars(
            select(TodoCategory)
            .where(TodoCategory.group_id == home_id)
            .order_by(TodoCategory.name, TodoCategory.id)
        )
    ).all()
    return TodoCategoryListResponse(items=[await _category_response(row) for row in rows])


@router.post("/{home_id}/todo-categories", response_model=TodoCategoryResponse, status_code=201)
async def create_category(
    home_id: uuid.UUID,
    body: TodoCategoryCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> TodoCategoryResponse:
    await _require_member(home_id, auth, db)
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)
    name = " ".join(body.name.strip().split())
    exists = await db.scalar(
        select(TodoCategory).where(TodoCategory.group_id == home_id, TodoCategory.name.ilike(name))
    )
    if exists:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A To-do category with that name already exists"
        )
    row = TodoCategory(group_id=home_id, name=name, created_by=auth.user.id)
    db.add(row)
    await db.flush()
    audit(db, request, "todo_category.created", auth.user.id, home_id, "todo_category", row.id)
    await db.commit()
    await db.refresh(row)
    return await _category_response(row)


@router.patch("/{home_id}/todo-categories/{category_id}", response_model=TodoCategoryResponse)
async def update_category(
    home_id: uuid.UUID,
    category_id: uuid.UUID,
    body: TodoCategoryUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> TodoCategoryResponse:
    await _require_member(home_id, auth, db)
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)
    row = await db.scalar(
        select(TodoCategory).where(TodoCategory.id == category_id, TodoCategory.group_id == home_id)
    )
    if row is None or row.created_by != auth.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That To-do category could not be found")
    if row.updated_at != body.expected_updated_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This category changed. Reload and try again."
        )
    name = " ".join(body.name.strip().split())
    duplicate = await db.scalar(
        select(TodoCategory).where(
            TodoCategory.group_id == home_id,
            TodoCategory.name.ilike(name),
            TodoCategory.id != row.id,
        )
    )
    if duplicate:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A To-do category with that name already exists"
        )
    row.name = name
    audit(db, request, "todo_category.updated", auth.user.id, home_id, "todo_category", row.id)
    await db.commit()
    await db.refresh(row)
    return await _category_response(row)


@router.delete("/{home_id}/todo-categories/{category_id}", status_code=204)
async def delete_category(
    home_id: uuid.UUID,
    category_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_member(home_id, auth, db)
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)
    row = await db.scalar(
        select(TodoCategory).where(TodoCategory.id == category_id, TodoCategory.group_id == home_id)
    )
    if row is None or row.created_by != auth.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That To-do category could not be found")
    audit(db, request, "todo_category.deleted", auth.user.id, home_id, "todo_category", row.id)
    await db.delete(row)
    await db.commit()


@router.get("/{home_id}/todos", response_model=TodoListResponse)
async def list_todos(
    home_id: uuid.UUID,
    include_completed: bool = Query(default=True),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> TodoListResponse:
    await _require_member(home_id, auth, db)
    statement = select(Todo).where(
        Todo.group_id == home_id,
        (Todo.scope == RoutineScope.household) | (Todo.owner_user_id == auth.user.id),
    )
    if not include_completed:
        statement = statement.where(Todo.completed_at.is_(None))
    rows = (
        await db.scalars(
            statement.order_by(Todo.completed_at.is_not(None), Todo.due_date, Todo.title)
        )
    ).all()
    return TodoListResponse(items=[await _response(db, row) for row in rows])


@router.post("/{home_id}/todos", response_model=TodoResponse, status_code=201)
async def create_todo(
    home_id: uuid.UUID,
    body: TodoCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> TodoResponse:
    await _require_member(home_id, auth, db)
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)
    await _category_for_home(db, home_id, body.category_id)
    member_ids = await _validate_members(db, home_id, body.member_ids)
    todo = Todo(
        group_id=home_id,
        title=" ".join(body.title.strip().split()),
        description=body.description,
        scope=body.scope,
        owner_user_id=auth.user.id if body.scope == RoutineScope.personal else None,
        category_id=body.category_id,
        due_date=body.due_date,
        created_by=auth.user.id,
    )
    db.add(todo)
    await db.flush()
    for user_id in member_ids:
        db.add(TodoMember(todo_id=todo.id, user_id=user_id))
    audit(db, request, "todo.created", auth.user.id, home_id, "todo", todo.id)
    await db.commit()
    await db.refresh(todo)
    return await _response(db, todo)


@router.patch("/{home_id}/todos/{todo_id}", response_model=TodoResponse)
async def update_todo(
    home_id: uuid.UUID,
    todo_id: uuid.UUID,
    body: TodoUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> TodoResponse:
    await _require_member(home_id, auth, db)
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)
    todo = await db.scalar(
        select(Todo)
        .where(Todo.id == todo_id, Todo.group_id == home_id)
        .with_for_update()
    )
    if todo is None or not _visible(todo, auth.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That To-do could not be found")
    if todo.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This To-do changed. Reload and try again.")
    await _category_for_home(db, home_id, body.category_id)
    member_ids = await _validate_members(db, home_id, body.member_ids)
    await db.execute(delete(TodoMember).where(TodoMember.todo_id == todo.id))
    for user_id in member_ids:
        db.add(TodoMember(todo_id=todo.id, user_id=user_id))
    todo.title = " ".join(body.title.strip().split())
    todo.description = body.description
    todo.scope = body.scope
    todo.owner_user_id = (
        todo.owner_user_id or auth.user.id if body.scope == RoutineScope.personal else None
    )
    todo.category_id = body.category_id
    todo.due_date = body.due_date
    audit(db, request, "todo.updated", auth.user.id, home_id, "todo", todo.id)
    await db.commit()
    await db.refresh(todo)
    return await _response(db, todo)


@router.delete("/{home_id}/todos/{todo_id}", status_code=204)
async def delete_todo(
    home_id: uuid.UUID,
    todo_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_member(home_id, auth, db)
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)
    todo = await db.scalar(select(Todo).where(Todo.id == todo_id, Todo.group_id == home_id))
    if todo is None or not _visible(todo, auth.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That To-do could not be found")
    audit(db, request, "todo.deleted", auth.user.id, home_id, "todo", todo.id)
    await db.delete(todo)
    await db.commit()


@router.post("/{home_id}/todos/{todo_id}/complete", response_model=TodoResponse)
async def complete_todo(
    home_id: uuid.UUID,
    todo_id: uuid.UUID,
    body: TodoCompletionRequest,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> TodoResponse:
    await _require_member(home_id, auth, db)
    todo = await db.scalar(select(Todo).where(Todo.id == todo_id, Todo.group_id == home_id))
    if todo is None or not _visible(todo, auth.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That To-do could not be found")
    todo.completed_at = datetime.now(UTC) if body.completed else None
    todo.completed_by = auth.user.id if body.completed else None
    await db.commit()
    await db.refresh(todo)
    return await _response(db, todo)
