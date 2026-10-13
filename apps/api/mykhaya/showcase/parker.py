"""The Parker family: the curated, entirely fictional showcase dataset.

Pure data — no database access. Every date is an offset in days from the
seed's reference date (see mykhaya.showcase.context.ShowcaseContext), so the
same dataset produces a current-looking Home whether it is seeded today
(rolling mode) or against a pinned screenshot date, and every cross-module
relationship (Sophie's birthday, the Lake District weekend, the Tiguan's MOT)
shifts together.

Nothing here identifies a real person, business or vehicle: names are
generic, places are generic ("Riverside Playing Fields"), member emails use
reserved domains that never deliver (see family.seed_household) and
registrations use the "Z" area letter, which the DVLA never issues as a
current-format memory tag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from mykhaya.colour_palette import ColourToken
from mykhaya.models import (
    ChildAgeBand,
    MealSlot,
    MealType,
    RecurrencePattern,
    ReminderCadence,
    ReminderRepeat,
    RoutineReminderTiming,
    WishlistOccasion,
    WishlistReservationStatus,
)

EMMA, JAMES, SOPHIE, OLIVER = "emma", "james", "sophie", "oliver"
ADULTS = (EMMA, JAMES)
CHILDREN = (SOPHIE, OLIVER)
EVERYONE = (EMMA, JAMES, SOPHIE, OLIVER)


# --- Household ----------------------------------------------------------------------


@dataclass(frozen=True)
class AvatarArt:
    background: str
    skin: str
    hair: str
    hair_style: str  # "long" | "short" | "bob" | "curly"
    top: str


@dataclass(frozen=True)
class MemberSpec:
    key: str
    name: str
    email_local: str
    is_child: bool
    # Birthday as an offset from the reference date plus an age on that
    # birthday, so "Sophie turns 10 next week" stays true in every seed.
    birthday_offset: int
    age_on_birthday: int
    colour: ColourToken
    avatar: AvatarArt
    age_band: ChildAgeBand | None = None


OWNER = MemberSpec(
    key=EMMA,
    name="Emma Parker",
    email_local="emma-parker",
    is_child=False,
    birthday_offset=74,
    age_on_birthday=39,
    colour=ColourToken.teal,
    avatar=AvatarArt("#CFE7E1", "#F1C7A5", "#6B3F24", "long", "#2F7F73"),
)
MEMBERS: tuple[MemberSpec, ...] = (
    MemberSpec(
        key=JAMES,
        name="James Parker",
        email_local="james-parker",
        is_child=False,
        birthday_offset=-41,
        age_on_birthday=41,
        colour=ColourToken.indigo,
        avatar=AvatarArt("#DCDDF3", "#E8B894", "#3B2A20", "short", "#4C5BA8"),
    ),
    MemberSpec(
        key=SOPHIE,
        name="Sophie Parker",
        email_local="sophie-parker",
        is_child=True,
        birthday_offset=9,
        age_on_birthday=10,
        colour=ColourToken.rose,
        avatar=AvatarArt("#F6DCE3", "#F3CDB0", "#A0622D", "bob", "#C2577A"),
        age_band=ChildAgeBand.under_13,
    ),
    MemberSpec(
        key=OLIVER,
        name="Oliver Parker",
        email_local="oliver-parker",
        is_child=True,
        birthday_offset=118,
        age_on_birthday=8,
        colour=ColourToken.amber,
        avatar=AvatarArt("#F7E7C4", "#EDC09C", "#5A3A22", "curly", "#D08A2E"),
        age_band=ChildAgeBand.under_13,
    ),
)


# --- Calendar -----------------------------------------------------------------------

# The Home's seeded event categories (the same names/colours a normal Home
# gets — routers.groups.DEFAULT_LABELS — all active, as on Family).
LABEL_FAMILY, LABEL_SCHOOL, LABEL_WORK = "Family", "School", "Work"
LABEL_APPOINTMENT, LABEL_BIRTHDAY, LABEL_ACTIVITY, LABEL_OTHER = (
    "Appointment",
    "Birthday",
    "Activity",
    "Other",
)


@dataclass(frozen=True)
class EventSpec:
    title: str
    day: int
    start: str | None = None  # "HH:MM"; None marks an all-day event
    end: str | None = None
    days: int = 1  # all-day span, inclusive of the start day
    label: str = LABEL_FAMILY
    people: tuple[str, ...] = EVERYONE
    recurrence: RecurrencePattern = RecurrencePattern.none
    # Weekly series: the weekday (Mon=0) the series runs on. The series is
    # anchored four weeks before the reference date so past weeks show
    # history and every future week stays populated.
    weekday: int | None = None
    location: str | None = None
    description: str | None = None
    personal: bool = False  # on Emma's private Personal Calendar
    reminder_minutes: int | None = None


EVENTS: tuple[EventSpec, ...] = (
    # Repeating household rhythm.
    EventSpec(
        "School drop-off",
        0,
        "08:30",
        "08:50",
        label=LABEL_SCHOOL,
        people=(EMMA, SOPHIE, OLIVER),
        recurrence=RecurrencePattern.weekdays,
        location="Oakfield Primary School",
    ),
    EventSpec(
        "Football practice",
        0,
        "17:00",
        "18:15",
        label=LABEL_ACTIVITY,
        people=(JAMES, OLIVER),
        recurrence=RecurrencePattern.weekly,
        weekday=1,
        location="Riverside Playing Fields",
        description="Boots, shin pads and a full water bottle.",
    ),
    EventSpec(
        "Coding club",
        0,
        "15:15",
        "16:30",
        label=LABEL_SCHOOL,
        people=(SOPHIE,),
        recurrence=RecurrencePattern.weekly,
        weekday=2,
        location="Oakfield Primary School",
    ),
    EventSpec(
        "Swimming lessons",
        0,
        "16:30",
        "17:15",
        label=LABEL_ACTIVITY,
        people=(EMMA, SOPHIE),
        recurrence=RecurrencePattern.weekly,
        weekday=3,
        location="Leisure Centre",
        reminder_minutes=60,
    ),
    EventSpec(
        "Family movie night",
        0,
        "19:00",
        "21:00",
        recurrence=RecurrencePattern.weekly,
        weekday=4,
        description="Oliver picks this week. Popcorn is on the shopping list.",
    ),
    EventSpec(
        "Grocery shopping",
        0,
        "09:30",
        "10:30",
        label=LABEL_OTHER,
        people=(EMMA, JAMES),
        recurrence=RecurrencePattern.weekly,
        weekday=5,
    ),
    EventSpec(
        "Weekend family walk",
        0,
        "10:00",
        "11:30",
        recurrence=RecurrencePattern.weekly,
        weekday=6,
        location="Hilltop Woods",
    ),
    # Recent history.
    EventSpec(
        "Grandma Ruth's birthday lunch",
        -20,
        "12:30",
        "15:00",
        label=LABEL_BIRTHDAY,
        location="Grandma's house",
    ),
    EventSpec(
        "School cake sale",
        -15,
        "15:00",
        "16:00",
        label=LABEL_SCHOOL,
        people=(EMMA, SOPHIE, OLIVER),
    ),
    EventSpec(
        "Family day out",
        -12,
        "10:00",
        "16:00",
        location="Science Museum",
        description="Train at 09:12. Packed lunch for everyone.",
    ),
    EventSpec(
        "Friends round for a barbecue",
        -8,
        "13:00",
        "17:00",
        description="The Hughes family are bringing dessert.",
    ),
    EventSpec(
        "Vet check-up for Biscuit",
        -5,
        "17:30",
        "18:00",
        label=LABEL_APPOINTMENT,
        people=(EMMA, JAMES),
        location="Meadow Vets",
    ),
    EventSpec(
        "Sophie's class assembly",
        -3,
        "09:00",
        "09:45",
        label=LABEL_SCHOOL,
        people=(EMMA, SOPHIE),
    ),
    EventSpec(
        "Oliver's playdate with Leo",
        -1,
        "15:30",
        "17:30",
        people=(EMMA, OLIVER),
    ),
    # Today, tomorrow and the rest of the week.
    EventSpec(
        "Quarterly planning meeting",
        0,
        "10:00",
        "11:30",
        label=LABEL_WORK,
        people=(EMMA,),
        personal=True,
    ),
    EventSpec(
        "Dentist appointment",
        0,
        "16:00",
        "16:40",
        label=LABEL_APPOINTMENT,
        people=(EMMA, OLIVER),
        location="Bright Smile Dental",
        description="Routine check-up for Oliver.",
        reminder_minutes=60,
    ),
    EventSpec(
        "Piano lesson",
        1,
        "17:30",
        "18:00",
        label=LABEL_ACTIVITY,
        people=(SOPHIE,),
    ),
    EventSpec(
        "Holiday planning",
        2,
        "20:00",
        "21:00",
        people=(EMMA, JAMES),
        description="Shortlist summer cottages and compare dates.",
    ),
    EventSpec(
        "Parents' evening",
        3,
        "17:30",
        "19:00",
        label=LABEL_SCHOOL,
        people=(EMMA, JAMES),
        location="Oakfield Primary School",
        reminder_minutes=120,
    ),
    EventSpec(
        "Friends coming over",
        4,
        "15:00",
        "18:00",
        description="Pizza night with the Hughes family.",
    ),
    # The weeks ahead.
    EventSpec(
        "School trip",
        8,
        label=LABEL_SCHOOL,
        people=(SOPHIE,),
        description="Natural History Museum. Packed lunch and a waterproof coat.",
    ),
    EventSpec(
        "Sophie's birthday dinner",
        9,
        "18:00",
        "20:00",
        label=LABEL_BIRTHDAY,
        location="Luigi's Trattoria",
        reminder_minutes=120,
    ),
    EventSpec(
        "Sophie's birthday party",
        10,
        "14:00",
        "16:30",
        label=LABEL_BIRTHDAY,
        location="Village hall",
        description="Twelve friends confirmed. Cake collection at 12:30.",
    ),
    EventSpec(
        "School inset day",
        11,
        label=LABEL_SCHOOL,
        people=(SOPHIE, OLIVER),
    ),
    EventSpec(
        "Football tournament",
        13,
        "09:30",
        "13:00",
        label=LABEL_ACTIVITY,
        people=(JAMES, OLIVER),
        location="Riverside Playing Fields",
    ),
    EventSpec(
        "Dentist check-up",
        16,
        "08:30",
        "09:00",
        label=LABEL_APPOINTMENT,
        people=(JAMES,),
        location="Bright Smile Dental",
    ),
    EventSpec(
        "Haircuts",
        17,
        "10:00",
        "11:00",
        label=LABEL_APPOINTMENT,
        people=(EMMA, SOPHIE, OLIVER),
    ),
    EventSpec(
        "Anniversary dinner",
        19,
        "19:30",
        "22:00",
        people=(EMMA, JAMES),
        location="The Riverside Bistro",
        description="Grandma Ruth is babysitting.",
    ),
    EventSpec(
        "Weekend in the Lake District",
        22,
        days=3,
        description="Cottage check-in from 4pm on Friday.",
    ),
    EventSpec(
        "Harvest festival",
        27,
        "14:00",
        "15:00",
        label=LABEL_SCHOOL,
        people=(EMMA, SOPHIE, OLIVER),
    ),
    EventSpec(
        "School holiday",
        30,
        days=5,
        label=LABEL_SCHOOL,
        people=(SOPHIE, OLIVER),
    ),
    EventSpec(
        "Family day out",
        32,
        "10:00",
        "16:00",
        location="City zoo",
    ),
    EventSpec(
        "Boiler service",
        36,
        "08:00",
        "10:00",
        label=LABEL_OTHER,
        people=(JAMES,),
    ),
    EventSpec(
        "Recycling centre trip",
        -10,
        "10:00",
        "11:00",
        label=LABEL_OTHER,
        people=(JAMES,),
        description="Old bikes and the broken garden chairs.",
    ),
    EventSpec(
        "Book club",
        6,
        "19:30",
        "21:30",
        label=LABEL_OTHER,
        people=(EMMA,),
        personal=True,
        location="The Old Library Café",
    ),
    EventSpec(
        "Grandma Ruth visiting",
        12,
        description="Staying in the spare room until Sunday.",
    ),
    EventSpec(
        "Oliver's class assembly",
        24,
        "09:00",
        "09:45",
        label=LABEL_SCHOOL,
        people=(EMMA, JAMES, OLIVER),
    ),
    EventSpec(
        "Sophie's sleepover",
        26,
        "17:00",
        "21:00",
        people=(SOPHIE,),
        description="Pick up from Mia's at 10am the next day.",
    ),
    EventSpec(
        "Team away day",
        40,
        label=LABEL_WORK,
        people=(EMMA,),
        personal=True,
    ),
)


# --- Nudges -------------------------------------------------------------------------

CATEGORY_HOUSEHOLD, CATEGORY_SCHOOL, CATEGORY_FAMILY, CATEGORY_ADMIN = (
    "Household",
    "School",
    "Family",
    "Admin",
)
NUDGE_CATEGORIES = (CATEGORY_HOUSEHOLD, CATEGORY_SCHOOL, CATEGORY_FAMILY, CATEGORY_ADMIN)


@dataclass(frozen=True)
class RoutineSpec:
    title: str
    repeat_unit: str  # "daily" | "weekly"
    people: tuple[str, ...]
    category: str
    weekday: int | None = None  # weekly series: the weekday (Mon=0) it runs on
    timing: RoutineReminderTiming = RoutineReminderTiming.same_day
    description: str | None = None
    completed_days: tuple[int, ...] = ()
    pinned: bool = False


ROUTINES: tuple[RoutineSpec, ...] = (
    RoutineSpec(
        "Morning school routine",
        "daily",
        (SOPHIE, OLIVER),
        CATEGORY_SCHOOL,
        description="Teeth, uniform, book bags and shoes by the door.",
        completed_days=(-6, -5, -4, -3, -2, -1, 0),
        pinned=True,
    ),
    RoutineSpec(
        "Feed the pets",
        "daily",
        (SOPHIE, OLIVER),
        CATEGORY_HOUSEHOLD,
        description="Biscuit gets one scoop morning and evening.",
        completed_days=(-4, -3, -2, -1, 0),
    ),
    RoutineSpec(
        "Make packed lunches",
        "daily",
        (JAMES,),
        CATEGORY_SCHOOL,
        completed_days=(-3, -2, -1),
    ),
    RoutineSpec(
        "Evening tidy-up",
        "daily",
        EVERYONE,
        CATEGORY_HOUSEHOLD,
        timing=RoutineReminderTiming.same_day,
        completed_days=(-3, -2, -1),
    ),
    RoutineSpec(
        "Sunday meal preparation",
        "weekly",
        ADULTS,
        CATEGORY_FAMILY,
        weekday=6,
        description="Batch-cook two dinners and plan next week's meals.",
    ),
    RoutineSpec(
        "Weekly household reset",
        "weekly",
        EVERYONE,
        CATEGORY_HOUSEHOLD,
        weekday=5,
        description="Change bedding, hoover upstairs, empty all the bins.",
    ),
)


@dataclass(frozen=True)
class ReminderSpec:
    title: str
    day: int
    time: str
    people: tuple[str, ...]
    category: str
    repeat: ReminderRepeat = ReminderRepeat.never
    cadence: ReminderCadence = ReminderCadence.once
    description: str | None = None
    completed_days: tuple[int, ...] = ()
    personal_owner: str | None = None


REMINDERS: tuple[ReminderSpec, ...] = (
    ReminderSpec(
        "Put recycling bins out",
        1,
        "19:00",
        (JAMES,),
        CATEGORY_HOUSEHOLD,
        repeat=ReminderRepeat.weekly,
        description="Blue bin this week — collection is first thing tomorrow.",
    ),
    ReminderSpec(
        "School trip payment",
        2,
        "09:00",
        (EMMA,),
        CATEGORY_SCHOOL,
        description="£18 for Sophie's Natural History Museum trip.",
    ),
    ReminderSpec(
        "Dentist appointment",
        0,
        "08:00",
        (EMMA,),
        CATEGORY_FAMILY,
        description="Oliver at 4pm — bring his dental card.",
    ),
    ReminderSpec(
        "Buy birthday present",
        4,
        "12:00",
        (JAMES,),
        CATEGORY_FAMILY,
        description="Sophie's art set — see her wishlist.",
    ),
    ReminderSpec(
        "Order school supplies",
        -2,
        "18:00",
        (EMMA,),
        CATEGORY_SCHOOL,
        description="Glue sticks, a maths set and two exercise books.",
    ),
    ReminderSpec(
        "Water the plants",
        0,
        "08:30",
        (SOPHIE,),
        CATEGORY_HOUSEHOLD,
        repeat=ReminderRepeat.weekly,
        completed_days=(-7, 0),
    ),
    ReminderSpec(
        "Renew library books",
        -1,
        "16:00",
        (OLIVER, EMMA),
        CATEGORY_FAMILY,
    ),
    ReminderSpec(
        "Pay council tax",
        6,
        "09:00",
        (JAMES,),
        CATEGORY_ADMIN,
        description="Check the new bill and direct debit amount.",
    ),
)


@dataclass(frozen=True)
class TodoSpec:
    title: str
    day: int
    category: str
    people: tuple[str, ...] = ()
    personal_owner: str | None = None
    completed_day: int | None = None
    completed_by: str | None = None
    description: str | None = None


TODOS: tuple[TodoSpec, ...] = (
    TodoSpec(
        "Book family holiday",
        5,
        CATEGORY_FAMILY,
        people=ADULTS,
        description="Compare the three cottages from Wednesday's planning session.",
    ),
    TodoSpec("Organise garage", 9, CATEGORY_HOUSEHOLD, people=(JAMES,)),
    TodoSpec("Pick up prescriptions", 0, CATEGORY_ADMIN, personal_owner=EMMA),
    TodoSpec(
        "Buy groceries",
        0,
        CATEGORY_HOUSEHOLD,
        people=ADULTS,
        completed_day=0,
        completed_by=JAMES,
    ),
    TodoSpec("Sort children's uniforms", -1, CATEGORY_SCHOOL, people=(EMMA,)),
    TodoSpec("Plan weekend activities", 3, CATEGORY_FAMILY, people=ADULTS),
    TodoSpec(
        "Clean out fridge",
        -1,
        CATEGORY_HOUSEHOLD,
        people=(JAMES,),
        completed_day=-1,
        completed_by=JAMES,
    ),
    TodoSpec(
        "Prepare birthday party",
        7,
        CATEGORY_FAMILY,
        people=(EMMA,),
        description="Party bags, balloons and the cake order — see the party list.",
    ),
    TodoSpec("Book pet sitter for Biscuit", 14, CATEGORY_HOUSEHOLD, people=(EMMA,)),
    TodoSpec("Fix Oliver's bike puncture", 2, CATEGORY_HOUSEHOLD, people=(JAMES,)),
    TodoSpec(
        "Pack for the Lake District",
        21,
        CATEGORY_FAMILY,
        people=EVERYONE,
        description="Use the packing list.",
    ),
)


# --- Meals --------------------------------------------------------------------------


@dataclass(frozen=True)
class MealArt:
    """The built-in illustration recipe for a meal (mykhaya.showcase.images)."""

    motif: str
    background: str
    primary: str
    secondary: str
    accent: str


@dataclass(frozen=True)
class RecipeSpec:
    slug: str
    name: str
    meal_type: MealType
    prep: int
    cook: int
    servings: int
    description: str
    ingredients: tuple[tuple[str | None, str | None, str], ...]
    steps: tuple[str, ...]
    tags: tuple[str, ...]
    art: MealArt
    favourite: bool = False


RECIPES: tuple[RecipeSpec, ...] = (
    RecipeSpec(
        "spaghetti-bolognese",
        "Spaghetti Bolognese",
        MealType.dinner,
        15,
        45,
        4,
        "A slow-simmered family classic with a rich tomato and beef sauce.",
        (
            ("400", "g", "spaghetti"),
            ("500", "g", "beef mince"),
            ("1", None, "onion, finely chopped"),
            ("2", None, "garlic cloves, crushed"),
            ("1", None, "carrot, grated"),
            ("400", "g", "chopped tomatoes"),
            ("2", "tbsp", "tomato purée"),
            (None, None, "Parmesan, to serve"),
        ),
        (
            "Brown the mince in a large pan, then lift it out.",
            "Soften the onion, carrot and garlic in the same pan for 8 minutes.",
            "Return the mince, add the tomatoes and purée, and simmer for 30 minutes.",
            "Cook the spaghetti, toss with the sauce and finish with Parmesan.",
        ),
        ("family favourite", "batch cook"),
        MealArt("pasta", "#F4E3D3", "#E8C27A", "#B5432F", "#4E8A3E"),
        favourite=True,
    ),
    RecipeSpec(
        "creamy-chicken-pasta",
        "Creamy Chicken Pasta",
        MealType.dinner,
        10,
        20,
        4,
        "Quick weeknight penne in a garlicky cream sauce with spinach.",
        (
            ("350", "g", "penne"),
            ("2", None, "chicken breasts, sliced"),
            ("200", "ml", "single cream"),
            ("2", None, "garlic cloves, crushed"),
            ("100", "g", "baby spinach"),
            ("40", "g", "Parmesan, grated"),
        ),
        (
            "Cook the penne until just tender.",
            "Fry the chicken until golden and cooked through, then add the garlic.",
            "Stir in the cream and Parmesan and bubble for 2 minutes.",
            "Fold through the spinach and drained pasta.",
        ),
        ("quick",),
        MealArt("pasta", "#EDE7DA", "#F1D9A0", "#F7F1E3", "#3F7D3A"),
    ),
    RecipeSpec(
        "homemade-burgers",
        "Homemade Burgers",
        MealType.dinner,
        20,
        12,
        4,
        "Juicy beef burgers in toasted brioche buns with all the trimmings.",
        (
            ("500", "g", "beef mince"),
            ("1", None, "small onion, grated"),
            ("1", None, "egg"),
            ("4", None, "brioche buns"),
            ("4", "slices", "cheddar"),
            (None, None, "lettuce, tomato and pickles"),
        ),
        (
            "Mix the mince, onion and egg, season and shape into four patties.",
            "Chill for 10 minutes so they hold their shape.",
            "Griddle for 5–6 minutes each side, adding cheese for the last minute.",
            "Toast the buns and build with your favourite toppings.",
        ),
        ("weekend", "family favourite"),
        MealArt("burger", "#F3E1C7", "#C9883B", "#6B3B22", "#5C9E3D"),
        favourite=True,
    ),
    RecipeSpec(
        "thai-green-curry",
        "Thai Green Curry",
        MealType.dinner,
        15,
        25,
        4,
        "Fragrant coconut curry with chicken, green beans and jasmine rice.",
        (
            ("3", "tbsp", "green curry paste"),
            ("400", "ml", "coconut milk"),
            ("3", None, "chicken thighs, sliced"),
            ("150", "g", "green beans"),
            ("1", None, "lime"),
            ("300", "g", "jasmine rice"),
            (None, None, "fresh coriander"),
        ),
        (
            "Fry the curry paste for a minute until fragrant.",
            "Add the chicken and stir to coat, then pour in the coconut milk.",
            "Simmer for 15 minutes, adding the beans for the last 5.",
            "Finish with lime juice and coriander; serve with rice.",
        ),
        ("spicy",),
        MealArt("bowl", "#E4EEDC", "#A9C46C", "#F6F2E6", "#3E7D2C"),
    ),
    RecipeSpec(
        "sunday-roast-chicken",
        "Sunday Roast Chicken",
        MealType.dinner,
        20,
        90,
        6,
        "Golden roast chicken with crispy potatoes, carrots and gravy.",
        (
            ("1", None, "whole chicken (1.6kg)"),
            ("1", "kg", "roasting potatoes"),
            ("4", None, "carrots"),
            ("1", None, "lemon"),
            (None, None, "fresh thyme"),
            ("2", "tbsp", "olive oil"),
        ),
        (
            "Heat the oven to 200°C. Stuff the chicken with lemon and thyme.",
            "Roast for 1 hour 20 minutes, basting halfway.",
            "Par-boil the potatoes, rough them up and roast for 50 minutes.",
            "Rest the chicken for 15 minutes while you make the gravy.",
        ),
        ("weekend", "family favourite"),
        MealArt("roast", "#F2E2CC", "#D59A4A", "#E5C27B", "#E07A2E"),
        favourite=True,
    ),
    RecipeSpec(
        "beef-lasagne",
        "Beef Lasagne",
        MealType.dinner,
        30,
        45,
        6,
        "Layers of rich ragù, silky white sauce and golden cheese.",
        (
            ("500", "g", "beef mince"),
            ("400", "g", "chopped tomatoes"),
            ("12", None, "lasagne sheets"),
            ("50", "g", "butter"),
            ("50", "g", "plain flour"),
            ("600", "ml", "milk"),
            ("100", "g", "mozzarella"),
        ),
        (
            "Make a ragù with the mince and tomatoes and simmer for 20 minutes.",
            "Melt the butter, stir in the flour, then whisk in the milk until thick.",
            "Layer ragù, pasta and white sauce three times.",
            "Top with mozzarella and bake at 190°C for 40 minutes.",
        ),
        ("batch cook",),
        MealArt("tray", "#F1DFCF", "#C9552F", "#F2C95E", "#7A4A2A"),
    ),
    RecipeSpec(
        "chicken-stir-fry",
        "Chicken Stir Fry",
        MealType.dinner,
        15,
        10,
        4,
        "Speedy noodles with crunchy vegetables and a sticky soy glaze.",
        (
            ("2", None, "chicken breasts, sliced"),
            ("250", "g", "egg noodles"),
            ("1", None, "red pepper, sliced"),
            ("1", None, "head of broccoli, in florets"),
            ("3", "tbsp", "soy sauce"),
            ("1", "tbsp", "honey"),
            ("1", "tsp", "grated ginger"),
        ),
        (
            "Cook the noodles and rinse under cold water.",
            "Stir-fry the chicken in a very hot wok for 4 minutes.",
            "Add the vegetables and ginger for another 3 minutes.",
            "Toss through the noodles, soy and honey until glossy.",
        ),
        ("quick",),
        MealArt("bowl", "#F5E6D2", "#D9A24C", "#E05A3A", "#4E9A3A"),
    ),
    RecipeSpec(
        "cottage-pie",
        "Cottage Pie",
        MealType.dinner,
        25,
        40,
        6,
        "Savoury beef and vegetable base under a fluffy cheesy mash.",
        (
            ("500", "g", "beef mince"),
            ("1", None, "onion, diced"),
            ("2", None, "carrots, diced"),
            ("300", "ml", "beef stock"),
            ("1", "kg", "potatoes"),
            ("50", "g", "cheddar, grated"),
        ),
        (
            "Brown the mince with the onion and carrots.",
            "Add the stock and simmer for 20 minutes until thick.",
            "Boil and mash the potatoes with butter and milk.",
            "Spoon the mash over the filling, add cheese and bake for 25 minutes.",
        ),
        ("batch cook", "family favourite"),
        MealArt("tray", "#EFE3D2", "#E9C873", "#8A4B2A", "#D8A84E"),
    ),
    RecipeSpec(
        "pancakes-with-berries",
        "Pancakes with Berries",
        MealType.breakfast,
        10,
        15,
        4,
        "Fluffy weekend pancakes stacked high with berries and maple syrup.",
        (
            ("200", "g", "self-raising flour"),
            ("1", "tsp", "baking powder"),
            ("1", None, "egg"),
            ("300", "ml", "milk"),
            ("150", "g", "mixed berries"),
            (None, None, "maple syrup"),
        ),
        (
            "Whisk the flour, baking powder, egg and milk into a thick batter.",
            "Cook ladlefuls in a buttered pan until bubbles appear, then flip.",
            "Stack and top with berries and a drizzle of maple syrup.",
        ),
        ("weekend", "breakfast"),
        MealArt("stack", "#F7EEDD", "#E2B068", "#7B2D52", "#3C5BA8"),
        favourite=True,
    ),
    RecipeSpec(
        "fish-and-chips",
        "Fish and Chips",
        MealType.dinner,
        20,
        30,
        4,
        "Crispy oven-baked fish with chunky chips and mushy peas.",
        (
            ("4", None, "white fish fillets"),
            ("80", "g", "panko breadcrumbs"),
            ("1", None, "egg, beaten"),
            ("800", "g", "potatoes, cut into chips"),
            ("300", "g", "frozen peas"),
            ("1", None, "lemon"),
        ),
        (
            "Toss the chips in oil and bake at 220°C for 30 minutes.",
            "Dip the fish in egg, then breadcrumbs, and bake for the last 15 minutes.",
            "Simmer the peas and roughly crush with butter.",
            "Serve with lemon wedges.",
        ),
        ("friday",),
        MealArt("plate", "#EAF0F3", "#E3B25A", "#F3D27A", "#6BA544"),
    ),
    RecipeSpec(
        "vegetable-pasta-bake",
        "Vegetable Pasta Bake",
        MealType.dinner,
        15,
        30,
        6,
        "Roasted vegetables and pasta in tomato sauce with a bubbling cheese top.",
        (
            ("400", "g", "fusilli"),
            ("1", None, "courgette"),
            ("1", None, "red pepper"),
            ("1", None, "red onion"),
            ("500", "g", "passata"),
            ("125", "g", "mozzarella"),
        ),
        (
            "Roast the chopped vegetables at 200°C for 20 minutes.",
            "Cook the pasta for 2 minutes less than the packet says.",
            "Mix the pasta, vegetables and passata in a baking dish.",
            "Top with mozzarella and bake for 15 minutes.",
        ),
        ("vegetarian", "batch cook"),
        MealArt("tray", "#EEF0DE", "#D9573A", "#F0D27C", "#5E9B3E"),
    ),
    RecipeSpec(
        "chicken-fajitas",
        "Chicken Fajitas",
        MealType.dinner,
        15,
        15,
        4,
        "Smoky chicken and peppers wrapped in warm tortillas.",
        (
            ("3", None, "chicken breasts, in strips"),
            ("2", None, "peppers, sliced"),
            ("1", None, "red onion, sliced"),
            ("2", "tsp", "fajita seasoning"),
            ("8", None, "flour tortillas"),
            (None, None, "soured cream and salsa"),
        ),
        (
            "Toss the chicken and vegetables in the seasoning.",
            "Fry in a hot pan for 10–12 minutes until charred at the edges.",
            "Warm the tortillas and let everyone build their own.",
        ),
        ("quick", "family favourite"),
        MealArt("wrap", "#F5E4CF", "#E8C48A", "#D2492F", "#E7A13A"),
        favourite=True,
    ),
    RecipeSpec(
        "margherita-pizza",
        "Margherita Pizza",
        MealType.dinner,
        25,
        12,
        4,
        "Homemade dough, simple tomato sauce, mozzarella and fresh basil.",
        (
            ("300", "g", "strong white flour"),
            ("7", "g", "fast-action yeast"),
            ("200", "ml", "warm water"),
            ("150", "ml", "passata"),
            ("2", None, "balls of mozzarella"),
            (None, None, "fresh basil"),
        ),
        (
            "Mix the flour, yeast, water and a pinch of salt; knead for 5 minutes.",
            "Rest for 30 minutes, then roll into two thin bases.",
            "Spread with passata, tear over the mozzarella.",
            "Bake at the hottest oven setting for 10–12 minutes and add basil.",
        ),
        ("weekend", "vegetarian"),
        MealArt("pizza", "#F2E5D3", "#E7B866", "#C93C2A", "#3E8A3A"),
    ),
    RecipeSpec(
        "tomato-basil-soup",
        "Tomato and Basil Soup",
        MealType.lunch,
        10,
        30,
        4,
        "Velvety roasted tomato soup — perfect with crusty bread.",
        (
            ("1", "kg", "ripe tomatoes"),
            ("1", None, "onion"),
            ("2", None, "garlic cloves"),
            ("500", "ml", "vegetable stock"),
            (None, None, "fresh basil"),
            ("2", "tbsp", "crème fraîche"),
        ),
        (
            "Roast the tomatoes, onion and garlic at 200°C for 25 minutes.",
            "Blend with the stock until smooth, then warm through.",
            "Swirl in crème fraîche and scatter with basil.",
        ),
        ("vegetarian", "lunch"),
        MealArt("soup", "#EFE6DA", "#D6452E", "#F6EDE0", "#3F8A3A"),
    ),
    RecipeSpec(
        "greek-salad",
        "Greek Salad",
        MealType.lunch,
        15,
        0,
        4,
        "Crunchy cucumber, tomatoes, olives and feta with oregano dressing.",
        (
            ("1", None, "cucumber"),
            ("4", None, "tomatoes"),
            ("1", None, "red onion"),
            ("100", "g", "Kalamata olives"),
            ("200", "g", "feta"),
            ("3", "tbsp", "olive oil"),
        ),
        (
            "Chop the cucumber and tomatoes into chunks; slice the onion thinly.",
            "Add the olives and top with a slab of feta.",
            "Dress with olive oil, oregano and a squeeze of lemon.",
        ),
        ("vegetarian", "no cook"),
        MealArt("salad", "#E7F0E3", "#5DA34A", "#D9442F", "#F4F1E6"),
    ),
    RecipeSpec(
        "chocolate-brownies",
        "Chocolate Brownies",
        MealType.dessert,
        15,
        25,
        16,
        "Fudgy, crackle-topped brownies for birthdays and weekends.",
        (
            ("200", "g", "dark chocolate"),
            ("175", "g", "butter"),
            ("250", "g", "caster sugar"),
            ("3", None, "eggs"),
            ("100", "g", "plain flour"),
            ("30", "g", "cocoa powder"),
        ),
        (
            "Melt the chocolate and butter together.",
            "Whisk the eggs and sugar until pale, then fold in the chocolate.",
            "Sift in the flour and cocoa and fold gently.",
            "Bake at 180°C for 25 minutes; cool before cutting into squares.",
        ),
        ("baking", "party"),
        MealArt("brownies", "#F3E7DA", "#5A3220", "#3E2216", "#E9D9C2"),
        favourite=True,
    ),
    RecipeSpec(
        "beef-tacos",
        "Beef Tacos",
        MealType.dinner,
        10,
        15,
        4,
        "Spiced beef in crunchy shells with lettuce, cheese and salsa.",
        (
            ("500", "g", "beef mince"),
            ("2", "tsp", "taco seasoning"),
            ("8", None, "taco shells"),
            (None, None, "shredded lettuce"),
            ("100", "g", "cheddar, grated"),
            (None, None, "tomato salsa"),
        ),
        (
            "Brown the mince and stir in the seasoning with a splash of water.",
            "Warm the shells in the oven for 3 minutes.",
            "Fill with beef, lettuce, cheese and salsa.",
        ),
        ("quick",),
        MealArt("tacos", "#F6E7D0", "#E9C065", "#8A4A2C", "#6AAE45"),
    ),
    RecipeSpec(
        "chicken-caesar-salad",
        "Chicken Caesar Salad",
        MealType.lunch,
        15,
        15,
        4,
        "Crisp lettuce, griddled chicken, croutons and a creamy dressing.",
        (
            ("2", None, "chicken breasts"),
            ("2", None, "romaine lettuces"),
            ("2", "slices", "sourdough, cubed"),
            ("40", "g", "Parmesan shavings"),
            ("4", "tbsp", "Caesar dressing"),
        ),
        (
            "Griddle the chicken for 6–7 minutes each side, then slice.",
            "Toss the bread in oil and bake into croutons.",
            "Toss the lettuce with dressing and top with chicken, croutons and Parmesan.",
        ),
        ("lunch",),
        MealArt("salad", "#ECF1E2", "#7CB55A", "#E8C27A", "#F4EEDF"),
    ),
    RecipeSpec(
        "baked-salmon",
        "Baked Salmon",
        MealType.dinner,
        10,
        18,
        4,
        "Lemon and herb salmon with new potatoes and tenderstem broccoli.",
        (
            ("4", None, "salmon fillets"),
            ("600", "g", "new potatoes"),
            ("200", "g", "tenderstem broccoli"),
            ("1", None, "lemon"),
            ("1", "tbsp", "chopped dill"),
        ),
        (
            "Boil the potatoes for 15 minutes.",
            "Bake the salmon with lemon slices at 200°C for 15–18 minutes.",
            "Steam the broccoli for the last 4 minutes.",
            "Serve with dill and extra lemon.",
        ),
        ("healthy",),
        MealArt("salmon", "#E6EFF1", "#F08A5D", "#5E9B3E", "#F3E3A2"),
    ),
    RecipeSpec(
        "breakfast-omelette",
        "Breakfast Omelette",
        MealType.breakfast,
        5,
        8,
        2,
        "Fluffy three-egg omelette with cheese, ham and chives.",
        (
            ("3", None, "eggs"),
            ("30", "g", "cheddar, grated"),
            ("2", "slices", "ham, chopped"),
            (None, None, "chives"),
            ("1", "tsp", "butter"),
        ),
        (
            "Whisk the eggs with a pinch of salt.",
            "Melt the butter in a non-stick pan and pour in the eggs.",
            "Scatter over the cheese and ham, fold and serve with chives.",
        ),
        ("breakfast", "quick"),
        MealArt("omelette", "#F5EEDB", "#F2CB55", "#E39A6B", "#4C8F3A"),
    ),
)


@dataclass(frozen=True)
class MealPlanSpec:
    # Offset in days from the Monday of the reference week.
    day: int
    slot: MealSlot
    recipe: str | None = None  # RecipeSpec.slug
    quick_name: str | None = None
    cook: str | None = None
    people: tuple[str, ...] = EVERYONE
    time: str = "18:00"
    makes_leftovers: bool = False


MEAL_PLAN: tuple[MealPlanSpec, ...] = (
    MealPlanSpec(0, MealSlot.dinner, "spaghetti-bolognese", cook=JAMES, makes_leftovers=True),
    MealPlanSpec(1, MealSlot.dinner, "chicken-stir-fry", cook=EMMA),
    MealPlanSpec(2, MealSlot.dinner, "vegetable-pasta-bake", cook=JAMES),
    MealPlanSpec(3, MealSlot.dinner, "thai-green-curry", cook=EMMA),
    MealPlanSpec(4, MealSlot.dinner, "margherita-pizza", cook=JAMES),
    MealPlanSpec(5, MealSlot.breakfast, "pancakes-with-berries", cook=EMMA, time="09:00"),
    MealPlanSpec(5, MealSlot.lunch, "tomato-basil-soup", cook=JAMES, time="12:30"),
    MealPlanSpec(5, MealSlot.dinner, "homemade-burgers", cook=JAMES),
    MealPlanSpec(6, MealSlot.dinner, "sunday-roast-chicken", cook=EMMA, time="17:00"),
    MealPlanSpec(7, MealSlot.dinner, "cottage-pie", cook=JAMES, makes_leftovers=True),
    MealPlanSpec(8, MealSlot.dinner, "chicken-fajitas", cook=EMMA),
    MealPlanSpec(9, MealSlot.dinner, "baked-salmon", cook=JAMES),
    MealPlanSpec(10, MealSlot.dinner, "beef-tacos", cook=EMMA),
    MealPlanSpec(11, MealSlot.dinner, "fish-and-chips", cook=JAMES),
    MealPlanSpec(12, MealSlot.breakfast, "breakfast-omelette", cook=JAMES, time="09:00"),
    MealPlanSpec(12, MealSlot.dinner, "beef-lasagne", cook=EMMA),
    MealPlanSpec(13, MealSlot.lunch, "chicken-caesar-salad", cook=EMMA, time="13:00"),
    MealPlanSpec(13, MealSlot.dinner, "creamy-chicken-pasta", cook=JAMES),
)
# The birthday dinner is out at a restaurant, so the plan shows a quick meal
# that night rather than a recipe. An offset from the reference date (not
# Monday), kept in step with Sophie's birthday and the Calendar event.
BIRTHDAY_DINNER_DAY = 9
BIRTHDAY_DINNER_QUICK_MEAL = "Birthday dinner at Luigi's"


# --- Lists --------------------------------------------------------------------------


@dataclass(frozen=True)
class ListItemSpec:
    text: str
    quantity: str | None = None
    note: str | None = None
    assignee: str | None = None
    checked_by: str | None = None


@dataclass(frozen=True)
class ListSpec:
    name: str
    icon: str
    items: tuple[ListItemSpec, ...]


LISTS: tuple[ListSpec, ...] = (
    ListSpec(
        "Weekly groceries",
        "groceries",
        (
            ListItemSpec("Semi-skimmed milk", "2"),
            ListItemSpec("Wholemeal bread"),
            ListItemSpec("Bananas", checked_by=JAMES),
            ListItemSpec("Free-range eggs", "12"),
            ListItemSpec("Popcorn", note="For movie night", assignee=JAMES),
            ListItemSpec("Chicken breasts", "4", checked_by=EMMA),
            ListItemSpec("Basmati rice"),
            ListItemSpec("Greek yoghurt", checked_by=EMMA),
            ListItemSpec("Mixed berries", note="For Saturday's pancakes"),
            ListItemSpec("Cheddar"),
        ),
    ),
    ListSpec(
        "Sophie's birthday party",
        "party",
        (
            ListItemSpec("Order the cake", note="Unicorn sponge, collect 12:30", checked_by=EMMA),
            ListItemSpec("Party bags", "12", assignee=EMMA),
            ListItemSpec("Balloons and bunting", assignee=JAMES),
            ListItemSpec("Candles — number 10", checked_by=JAMES),
            ListItemSpec("Juice and squash"),
            ListItemSpec("Paper plates and cups"),
        ),
    ),
    ListSpec(
        "Lake District packing",
        "packing",
        (
            ListItemSpec("Walking boots", note="Everyone"),
            ListItemSpec("Waterproof coats"),
            ListItemSpec("Board games", assignee=OLIVER),
            ListItemSpec("Phone chargers", assignee=JAMES),
            ListItemSpec("Biscuit's food and bowl", assignee=SOPHIE),
            ListItemSpec("Picnic blanket"),
        ),
    ),
    ListSpec(
        "School things",
        "school",
        (
            ListItemSpec("Glue sticks", "3", checked_by=EMMA),
            ListItemSpec("Maths set"),
            ListItemSpec("Exercise books", "2"),
            ListItemSpec("PE socks for Oliver"),
        ),
    ),
)


# --- Wishlists ----------------------------------------------------------------------


@dataclass(frozen=True)
class WishlistItemSpec:
    name: str
    price: Decimal | None = None
    note: str | None = None
    quantity: int = 1
    reserved_by: str | None = None
    reservation: WishlistReservationStatus = WishlistReservationStatus.reserved


@dataclass(frozen=True)
class WishlistSpec:
    owner: str
    title: str
    occasion: WishlistOccasion
    occasion_day: int | None
    description: str | None
    items: tuple[WishlistItemSpec, ...] = field(default_factory=tuple)


WISHLISTS: tuple[WishlistSpec, ...] = (
    WishlistSpec(
        SOPHIE,
        "Sophie's 10th birthday",
        WishlistOccasion.birthday,
        9,
        "Anything arty or crafty!",
        (
            WishlistItemSpec(
                "Deluxe art set",
                Decimal("34.99"),
                "The one with the wooden case",
                reserved_by=JAMES,
            ),
            WishlistItemSpec("Friendship bracelet kit", Decimal("12.50")),
            WishlistItemSpec(
                "Roller skates",
                Decimal("45.00"),
                "Size 2",
                reserved_by=EMMA,
                reservation=WishlistReservationStatus.bought,
            ),
            WishlistItemSpec("Detective story book series", Decimal("19.99")),
            WishlistItemSpec("Glow-in-the-dark stars", Decimal("8.99")),
        ),
    ),
    WishlistSpec(
        OLIVER,
        "Oliver's Christmas list",
        WishlistOccasion.christmas,
        None,
        None,
        (
            WishlistItemSpec("Football goal for the garden", Decimal("39.99")),
            WishlistItemSpec("Dinosaur fact book", Decimal("14.99")),
            WishlistItemSpec("Remote-control car", Decimal("29.99"), reserved_by=JAMES),
            WishlistItemSpec("Torch for camping", Decimal("9.99")),
        ),
    ),
)


# --- Budget (Ultimate) --------------------------------------------------------------


@dataclass(frozen=True)
class FixedCommitment:
    name: str
    amount: Decimal
    pay_day: int  # day of month the commitment is paid
    note: str | None = None


@dataclass(frozen=True)
class BudgetCategorySpec:
    name: str
    planned: Decimal
    fixed: tuple[FixedCommitment, ...] = ()


BUDGET_CATEGORIES: tuple[BudgetCategorySpec, ...] = (
    BudgetCategorySpec(
        "Housing",
        Decimal("1350"),
        (
            FixedCommitment("Mortgage", Decimal("1150"), 1),
            FixedCommitment("Council tax", Decimal("200"), 1),
        ),
    ),
    BudgetCategorySpec(
        "Utilities",
        Decimal("340"),
        (
            FixedCommitment("Electricity and gas", Decimal("191"), 3),
            FixedCommitment("Water", Decimal("45"), 6),
            FixedCommitment("Broadband", Decimal("38"), 12),
            FixedCommitment("Mobile phones", Decimal("52"), 18),
            FixedCommitment("TV licence", Decimal("14"), 20),
        ),
    ),
    BudgetCategorySpec("Groceries", Decimal("600")),
    BudgetCategorySpec("Transport", Decimal("420")),
    BudgetCategorySpec(
        "Children's activities",
        Decimal("250"),
        (
            FixedCommitment("Swimming lessons", Decimal("60"), 2),
            FixedCommitment("Piano lessons", Decimal("96"), 5),
            FixedCommitment("Football club", Decimal("44"), 9),
            FixedCommitment("Coding club", Decimal("50"), 15),
        ),
    ),
    BudgetCategorySpec("Eating Out", Decimal("220")),
    BudgetCategorySpec("Entertainment", Decimal("180")),
    BudgetCategorySpec(
        "Insurance",
        Decimal("170"),
        (
            FixedCommitment("Car insurance — BMW", Decimal("68"), 8),
            FixedCommitment("Car insurance — Tiguan", Decimal("44"), 8),
            FixedCommitment("Home insurance", Decimal("32"), 14),
            FixedCommitment("Life insurance", Decimal("26"), 22),
        ),
    ),
    BudgetCategorySpec("Health", Decimal("100")),
    BudgetCategorySpec("Household", Decimal("180")),
    BudgetCategorySpec("Holidays", Decimal("300")),
    BudgetCategorySpec(
        "Savings",
        Decimal("1000"),
        (
            FixedCommitment("Rainy-day savings", Decimal("600"), 26, "Easy-access saver"),
            FixedCommitment("Junior ISAs", Decimal("200"), 26, "£100 each for Sophie and Oliver"),
            FixedCommitment("Pension top-up", Decimal("200"), 27),
        ),
    ),
)


@dataclass(frozen=True)
class IncomeSpec:
    name: str
    amount: Decimal
    payday: int


INCOME: tuple[IncomeSpec, ...] = (
    IncomeSpec("Emma salary", Decimal("2850"), 25),
    IncomeSpec("James salary", Decimal("3250"), 28),
)


@dataclass(frozen=True)
class SpendSpec:
    category: str
    description: str
    day: int  # day of month (monthly templates) or offset from the reference date
    amount: Decimal


def _spend(category: str, description: str, day: int, amount: str) -> SpendSpec:
    return SpendSpec(category, description, day, Decimal(amount))


# A typical month of day-to-day spending. Applied in full to the previous
# month and up to the reference day in the current month. Previous month:
# Groceries ends near its limit, Eating Out modestly over, the rest under.
MONTHLY_SPENDING: tuple[SpendSpec, ...] = (
    _spend("Groceries", "Supermarket weekly shop", 2, "118.40"),
    _spend("Groceries", "Bakery", 5, "9.80"),
    _spend("Groceries", "Supermarket weekly shop", 9, "126.15"),
    _spend("Groceries", "Corner shop top-up", 12, "14.60"),
    _spend("Groceries", "Supermarket weekly shop", 16, "109.90"),
    _spend("Groceries", "Farmers' market", 19, "22.50"),
    _spend("Groceries", "Supermarket weekly shop", 23, "121.35"),
    _spend("Groceries", "Corner shop top-up", 27, "18.20"),
    _spend("Groceries", "Supermarket top-up", 30, "12.10"),
    _spend("Groceries", "Butcher", 14, "24.80"),
    _spend("Groceries", "Milk and bread", 25, "6.40"),
    _spend("Transport", "BMW i4 home charging", 4, "46.20"),
    _spend("Transport", "Fuel — Tiguan", 7, "78.40"),
    _spend("Transport", "Train tickets", 11, "36.50"),
    _spend("Transport", "BMW i4 rapid charging", 17, "22.80"),
    _spend("Transport", "Fuel — Tiguan", 21, "74.90"),
    _spend("Transport", "Parking", 24, "8.60"),
    _spend("Transport", "MINI fuel", 28, "52.30"),
    _spend("Transport", "Bus fares", 10, "12.40"),
    _spend("Transport", "Car wash", 25, "9.00"),
    _spend("Eating Out", "Café brunch", 6, "34.60"),
    _spend("Eating Out", "Family pizza night out", 13, "62.40"),
    _spend("Eating Out", "Coffee with friends", 18, "11.80"),
    _spend("Eating Out", "Sunday pub lunch", 20, "78.90"),
    _spend("Eating Out", "Takeaway curry", 26, "41.50"),
    _spend("Eating Out", "Ice creams", 29, "19.20"),
    _spend("Entertainment", "Streaming subscriptions", 3, "27.97"),
    _spend("Entertainment", "Cinema tickets", 14, "38.00"),
    _spend("Entertainment", "Board game", 22, "24.99"),
    _spend("Entertainment", "Family swim session", 8, "16.50"),
    _spend("Entertainment", "Kids' magazine", 11, "4.99"),
    _spend("Entertainment", "Bowling", 27, "32.00"),
    _spend("Health", "Pharmacy", 8, "12.45"),
    _spend("Health", "Opticians — new glasses", 19, "49.00"),
    _spend("Health", "Pharmacy", 25, "8.70"),
    _spend("Health", "Vitamins", 3, "9.99"),
    _spend("Household", "Cleaning supplies", 4, "21.30"),
    _spend("Household", "Garden centre", 15, "38.75"),
    _spend("Household", "Light bulbs and batteries", 23, "16.40"),
    _spend("Household", "Kids' shoes", 27, "45.00"),
    _spend("Household", "Hardware store", 10, "18.90"),
    _spend("Household", "Bin bags and foil", 18, "7.85"),
)

# Story spending, dated relative to the reference date (only entries that
# fall on or before the reference day are recorded).
STORY_SPENDING: tuple[SpendSpec, ...] = (
    _spend("Holidays", "Lake District cottage deposit", -6, "280.00"),
    _spend("Holidays", "Waterproofs for the Lake District", -2, "64.00"),
    _spend("Entertainment", "Sophie's birthday present — roller skates", -3, "45.00"),
    _spend("Household", "Party supplies for Sophie's party", -1, "27.60"),
    _spend("Children's activities", "School trip — Natural History Museum", -1, "18.00"),
    _spend("Holidays", "Summer holiday deposit", -40, "180.00"),
)


# --- Driveway (Ultimate) ------------------------------------------------------------


@dataclass(frozen=True)
class VehicleReminderSpec:
    event: str  # mykhaya.driveway_reminders.DrivewayReminderEventType value
    title: str
    day: int
    description: str | None = None


@dataclass(frozen=True)
class VehicleSpec:
    slug: str
    owner: str
    nickname: str
    make: str
    model: str
    colour: str
    colour_hex: str
    year: int
    fuel_type: str
    engine_size: str | None
    registration: str
    first_registered: tuple[int, int, int]
    body_style: str  # illustration silhouette: "saloon" | "suv" | "hatch"
    tax_due_day: int
    mot_due_day: int
    reminders: tuple[VehicleReminderSpec, ...]
    calendar_event: EventSpec | None = None


VEHICLES: tuple[VehicleSpec, ...] = (
    VehicleSpec(
        "bmw-i4",
        EMMA,
        "Emma's BMW",
        "BMW",
        "i4",
        "Grey",
        "#5F6B78",
        2022,
        "Electric",
        None,
        "ZM22 PKR",
        (2022, 6, 17),
        "saloon",
        tax_due_day=152,
        mot_due_day=241,
        reminders=(
            VehicleReminderSpec(
                "registration", "Renew road tax — BMW", 145, "Tax is current until renewal."
            ),
        ),
    ),
    VehicleSpec(
        "vw-tiguan",
        JAMES,
        "Family Tiguan",
        "Volkswagen",
        "Tiguan",
        "Blue",
        "#2F5E8C",
        2019,
        "Diesel",
        "2.0",
        "ZT19 PKR",
        (2019, 4, 3),
        "suv",
        tax_due_day=76,
        mot_due_day=18,
        reminders=(
            VehicleReminderSpec(
                "inspection",
                "Book the Tiguan's MOT",
                4,
                "MOT is due soon — Parkside Garage has Saturday slots.",
            ),
        ),
        calendar_event=EventSpec(
            "Tiguan MOT",
            14,
            "08:30",
            "10:00",
            label=LABEL_APPOINTMENT,
            people=(JAMES,),
            location="Parkside Garage",
        ),
    ),
    VehicleSpec(
        "mini-cooper",
        EMMA,
        "The MINI",
        "MINI",
        "Cooper",
        "Red",
        "#B8322A",
        2021,
        "Petrol",
        "1.5",
        "ZN21 PKR",
        (2021, 3, 26),
        "hatch",
        tax_due_day=201,
        mot_due_day=163,
        reminders=(
            VehicleReminderSpec(
                "service",
                "MINI annual service",
                12,
                "Service light is on — book the annual service.",
            ),
        ),
        calendar_event=EventSpec(
            "MINI service",
            15,
            "08:00",
            "12:00",
            label=LABEL_APPOINTMENT,
            people=(EMMA,),
            location="Parkside Garage",
        ),
    ),
)
