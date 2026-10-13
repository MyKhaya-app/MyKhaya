"""Ultimate-only showcase seeders: Budget and Driveway.

Budget belongs to one adult, never to a Home (models.BudgetProfile), so the
showcase Budget is Emma's own — the primary demo account — holding the
household's income and commitments. No partner share is created: James's
Budget is never exposed to Emma, or Emma's to James, by the seed.

Driveway status (tax, MOT) is seeded locally as manually-entered values,
never presented as a government lookup: lookup_provider, mot_refreshed_at and
MOT test history stay empty, so the UI shows no "DVSA" source, and
mykhaya.driveway_mot refuses provider lookups for showcase Homes outright
(see mykhaya.showcase.guards).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime

from sqlalchemy import select

from mykhaya.attachments.processing import process_attachment_upload
from mykhaya.budget_periods import BudgetPeriod, budget_period, budget_period_for_date
from mykhaya.budget_periods import expected_income_date as _expected_income_date
from mykhaya.driveway_reminders import DrivewayReminderEventType, upsert_driveway_reminder
from mykhaya.driveway_sensitive import new_vehicle_id, vehicle_sensitive_ciphertexts
from mykhaya.models import (
    BudgetCategory,
    BudgetIncomeSource,
    BudgetItem,
    BudgetItemType,
    BudgetMonthCategory,
    BudgetMonthIncome,
    BudgetMonthItem,
    BudgetProfile,
    BudgetSpendingEntry,
    RoutineScope,
    Vehicle,
)
from mykhaya.showcase import images, parker
from mykhaya.showcase.context import ShowcaseContext
from mykhaya.showcase.family import add_event
from mykhaya.vehicle_photo_storage import get_vehicle_photo_storage, vehicle_photo_filename

MONTH_START_DAY = 1


def _shift(period: BudgetPeriod, months: int) -> BudgetPeriod:
    index = period.year * 12 + (period.month - 1) + months
    return budget_period(index // 12, index % 12 + 1, MONTH_START_DAY)


def _day_in(period: BudgetPeriod, day: int) -> date:
    return date(
        period.start.year,
        period.start.month,
        min(day, monthrange(period.start.year, period.start.month)[1]),
    )


async def seed_budget(ctx: ShowcaseContext) -> int:
    # Imported here: the snapshot helper lives with the Budget router, and
    # importing it at module load would pull the router into every caller of
    # mykhaya.showcase.
    from mykhaya.routers.budget import _create_month_snapshot

    db = ctx.db
    owner = ctx.owner
    profile = await db.scalar(select(BudgetProfile).where(BudgetProfile.owner_user_id == owner.id))
    if profile is None:
        profile = BudgetProfile(owner_user_id=owner.id)
        db.add(profile)
    profile.currency = "GBP"
    profile.month_start_day = MONTH_START_DAY
    profile.default_view = "personal"
    profile.archived_at = None
    await db.flush()

    current = budget_period_for_date(ctx.reference_date, MONTH_START_DAY)
    periods = (_shift(current, -1), current, _shift(current, 1))

    categories: dict[str, BudgetCategory] = {}
    commitments: dict[str, tuple[str, parker.FixedCommitment]] = {}
    for order, spec in enumerate(parker.BUDGET_CATEGORIES):
        category = BudgetCategory(profile_id=profile.id, name=spec.name, sort_order=order)
        db.add(category)
        await db.flush()
        categories[spec.name] = category
        for commitment in spec.fixed:
            item = BudgetItem(
                profile_id=profile.id,
                category_id=category.id,
                name=commitment.name,
                item_type=BudgetItemType.fixed,
                default_amount=commitment.amount,
                recurring=True,
                starts_on=periods[0].start,
                notes=commitment.note,
            )
            db.add(item)
            await db.flush()
            commitments[str(item.id)] = (spec.name, commitment)
    for order, income in enumerate(parker.INCOME):
        db.add(
            BudgetIncomeSource(
                profile_id=profile.id,
                name=income.name,
                sort_order=order,
                usual_payday_day=income.payday,
                recurring=True,
            )
        )
    await db.flush()

    entries = 0
    for period in periods:
        # The Budget's own snapshot path: month categories, fixed-item
        # snapshots, planned totals and income rows, exactly as a month
        # created in the app.
        month = await _create_month_snapshot(db, profile, period.year, period.month, None, owner.id)
        await db.flush()
        month_categories = {
            row.category_id: row
            for row in (
                await db.scalars(
                    select(BudgetMonthCategory).where(BudgetMonthCategory.month_id == month.id)
                )
            ).all()
        }
        # Variable categories carry their plan on the month category.
        for spec in parker.BUDGET_CATEGORIES:
            if not spec.fixed:
                month_categories[categories[spec.name].id].planned_amount = spec.planned
        # Income: received once its payday has passed, expected otherwise.
        incomes = {
            row.source_name: row
            for row in (
                await db.scalars(
                    select(BudgetMonthIncome).where(BudgetMonthIncome.month_id == month.id)
                )
            ).all()
        }
        for income in parker.INCOME:
            row = incomes[income.name]
            row.expected_amount = income.amount
            payday = _expected_income_date(
                period.year, period.month, MONTH_START_DAY, income.payday
            )
            if payday <= ctx.reference_date:
                row.received_amount = income.amount
                row.received_date = payday
        # Fixed commitments are PAID exactly when a spending entry links to
        # the month's item (see routers.budget._item_payment_status).
        month_items = (
            await db.scalars(select(BudgetMonthItem).where(BudgetMonthItem.month_id == month.id))
        ).all()
        for month_item in month_items:
            category_name, commitment = commitments[str(month_item.budget_item_id)]
            paid_on = _day_in(period, commitment.pay_day)
            if paid_on > ctx.reference_date:
                continue
            db.add(
                BudgetSpendingEntry(
                    month_category_id=month_categories[categories[category_name].id].id,
                    description=commitment.name,
                    amount=month_item.planned_amount,
                    spent_on=paid_on,
                    budget_month_item_id=month_item.id,
                )
            )
            entries += 1
        # Day-to-day spending up to the reference day.
        for spend in parker.MONTHLY_SPENDING:
            spent_on = _day_in(period, spend.day)
            if spent_on > ctx.reference_date:
                continue
            db.add(
                BudgetSpendingEntry(
                    month_category_id=month_categories[categories[spend.category].id].id,
                    description=spend.description,
                    amount=spend.amount,
                    spent_on=spent_on,
                )
            )
            entries += 1
        for spend in parker.STORY_SPENDING:
            spent_on = ctx.day(spend.day)
            if spent_on > ctx.reference_date or not (period.start <= spent_on < period.end):
                continue
            db.add(
                BudgetSpendingEntry(
                    month_category_id=month_categories[categories[spend.category].id].id,
                    description=spend.description,
                    amount=spend.amount,
                    spent_on=spent_on,
                )
            )
            entries += 1
        await db.flush()
    ctx.add_count("budget_months", len(periods))
    ctx.add_count("budget_transactions", entries)
    return len(categories)


async def seed_driveway(ctx: ShowcaseContext) -> int:
    db = ctx.db
    storage = get_vehicle_photo_storage(ctx.settings)
    reminders = 0
    for spec in parker.VEHICLES:
        vehicle_id = new_vehicle_id()
        # The registration goes through the Driveway encryption boundary
        # exactly as routers.driveway.create_vehicle writes it.
        ciphertexts = vehicle_sensitive_ciphertexts(
            vehicle_id, registration=spec.registration, vin=None, settings=ctx.settings
        )
        raw = images.approved_photo("vehicles", spec.slug) or images.render_vehicle_illustration(
            spec.slug, spec.colour_hex, spec.body_style
        )
        photo_key = vehicle_photo_filename()
        await storage.save(photo_key, process_attachment_upload(raw))
        ctx.written.vehicle_photos.append(photo_key)
        vehicle = Vehicle(
            id=vehicle_id,
            group_id=ctx.home_id,
            owner_user_id=ctx.users[spec.owner].id,
            scope=RoutineScope.household,
            nickname=spec.nickname,
            make=spec.make,
            model=spec.model,
            colour=spec.colour,
            year=spec.year,
            fuel_type=spec.fuel_type,
            engine_size=spec.engine_size,
            country_code="GB",
            registration=spec.registration,
            first_registration_date=date(*spec.first_registered),
            # Locally-seeded status, deliberately without a lookup provider or
            # refresh timestamp: shown as entered, never as DVLA/DVSA-verified.
            tax_status="Taxed",
            tax_due_date=ctx.day(spec.tax_due_day),
            inspection_status="valid",
            inspection_due_date=ctx.day(spec.mot_due_day),
            photo_key=photo_key,
            photo_updated_at=datetime.now(UTC),
            **ciphertexts,
        )
        db.add(vehicle)
        await db.flush()
        for reminder_spec in spec.reminders:
            await upsert_driveway_reminder(
                db,
                group_id=ctx.home_id,
                vehicle=vehicle,
                event_type=DrivewayReminderEventType(reminder_spec.event),
                due_date=ctx.day(reminder_spec.day),
                title=reminder_spec.title,
                description=reminder_spec.description,
                created_by=ctx.owner.id,
            )
            reminders += 1
        if spec.calendar_event is not None:
            await add_event(ctx, spec.calendar_event)
            ctx.add_count("calendar_events", 1)
    await db.flush()
    ctx.add_count("vehicle_reminders", reminders)
    return len(parker.VEHICLES)
