"""Pydantic contracts for the personal Budget module."""

import uuid
from datetime import date

from pydantic import BaseModel, Field, model_validator

from mykhaya.models import BudgetActualSource, BudgetSharingLevel


class BudgetProfileResponse(BaseModel):
    id: uuid.UUID
    owner_user_id: uuid.UUID
    currency: str
    month_start_day: int = Field(ge=1, le=28)
    archived: bool


class BudgetSettingsUpdate(BaseModel):
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    month_start_day: int = Field(default=1, ge=1, le=28)


class BudgetIncomingShareResponse(BaseModel):
    home_id: uuid.UUID
    owner_user_id: uuid.UUID
    owner_display_name: str
    level: BudgetSharingLevel


class BudgetCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = Field(default=0, ge=0, le=10000)


class BudgetCategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    sort_order: int
    archived: bool


class BudgetIncomeSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = Field(default=0, ge=0, le=10000)


class BudgetIncomeSourceResponse(BaseModel):
    id: uuid.UUID
    name: str
    sort_order: int
    archived: bool


class BudgetMonthIncomeResponse(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    expected_amount: float
    received_amount: float


class BudgetMonthCategoryResponse(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    category_name: str
    planned_amount: float
    actual_source: BudgetActualSource
    manual_actual: float | None
    entries_actual: float
    actual_amount: float


class BudgetMonthResponse(BaseModel):
    id: uuid.UUID
    year: int
    month: int
    categories: list[BudgetMonthCategoryResponse]
    income: list[BudgetMonthIncomeResponse] = Field(default_factory=list)


class BudgetSpendingEntryCreate(BaseModel):
    category_id: uuid.UUID
    description: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0, le=100000000)
    spent_on: date


class BudgetSpendingEntryUpdate(BaseModel):
    category_id: uuid.UUID
    description: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0, le=100000000)
    spent_on: date


class BudgetSpendingEntryResponse(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    description: str
    amount: float
    spent_on: date


class BudgetActualUpdate(BaseModel):
    source: BudgetActualSource
    manual_actual: float | None = Field(default=None, ge=0, le=100000000)

    @model_validator(mode="after")
    def manual_value_matches_source(self) -> "BudgetActualUpdate":
        if self.source == BudgetActualSource.manual and self.manual_actual is None:
            raise ValueError("manual_actual is required when source is manual")
        if self.source == BudgetActualSource.entries and self.manual_actual is not None:
            raise ValueError("manual_actual must be omitted when source is entries")
        return self


class BudgetPlanAmountUpdate(BaseModel):
    planned_amount: float = Field(ge=0, le=100000000)


class BudgetMonthIncomeUpdate(BaseModel):
    expected_amount: float = Field(ge=0, le=100000000)
    received_amount: float = Field(ge=0, le=100000000)


class BudgetPartnerShareCreate(BaseModel):
    partner_user_id: uuid.UUID
    level: BudgetSharingLevel


class BudgetPartnerShareResponse(BaseModel):
    id: uuid.UUID
    partner_user_id: uuid.UUID
    level: BudgetSharingLevel
    active: bool
