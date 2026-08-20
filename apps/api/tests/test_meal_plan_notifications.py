from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from uuid import uuid4

from mykhaya.models import MealSlot
from mykhaya.notifications.briefing import format_daily_briefing
from mykhaya.notifications.meal_plans import (
    MealBriefingItem,
    created_copy,
    meal_name,
    removed_copy,
    updated_copy,
)


def _entry(**overrides: object) -> SimpleNamespace:
    values = {
        "id": uuid4(),
        "date": date(2026, 8, 21),
        "meal_slot": MealSlot.dinner,
        "time": time(18, 30),
        "quick_meal_name": "Takeaway",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_quick_meal_copy_includes_slot_date_and_time() -> None:
    title, body = created_copy(_entry(), None)
    assert title == "Dinner planned for Friday"
    assert body == "Takeaway at 18:30"


def test_update_and_remove_copy_is_concise() -> None:
    entry = _entry()
    assert updated_copy(entry, None) == ("Friday's dinner changed", "Takeaway at 18:30")
    assert removed_copy(entry, None) == ("Friday's dinner was removed", "Takeaway")


def test_meal_names_are_safe_for_notification_text() -> None:
    entry = _entry(quick_meal_name="Bad\nMeal\x00")
    assert meal_name(entry, None) == "Bad Meal"


def test_briefing_meals_use_slot_order_and_existing_item_cap() -> None:
    items = [
        MealBriefingItem(uuid4(), "Dinner", "Lasagne", time(18, 30), False, "Megan"),
        MealBriefingItem(uuid4(), "Breakfast", "Oats", None, True, None),
        MealBriefingItem(uuid4(), "Lunch", "School lunch", time(12, 0), False, None),
    ]
    title, body = format_daily_briefing(
        [], local_date=date(2026, 8, 20), tz=UTC, meal_items=items
    )
    assert title == "You have 3 events today."
    assert "• Breakfast: Oats · You're cooking" in body
    assert "• Lunch: School lunch at 12:00" in body
    assert "• Dinner: Lasagne at 18:30 · Megan cooking" in body


def test_briefing_meals_share_the_five_item_cap() -> None:
    meals = [MealBriefingItem(uuid4(), "Dinner", f"Meal {i}", None, False, None) for i in range(3)]
    events = [
        SimpleNamespace(
            event_id=uuid4(),
            title=f"Event {i}",
            start_at=datetime(2026, 8, 20, i, tzinfo=UTC),
            is_all_day=False,
        )
        for i in range(3)
    ]
    title, body = format_daily_briefing(
        events, local_date=date(2026, 8, 20), tz=UTC, meal_items=meals
    )
    assert title == "You have 6 events today."
    assert body.count("• ") == 6  # five visible items plus the remainder line
    assert "• +1 more events" in body
