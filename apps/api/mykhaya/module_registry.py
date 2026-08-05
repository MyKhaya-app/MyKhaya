from dataclasses import dataclass
from enum import StrEnum

from mykhaya.models import FeatureKey


class ReleaseState(StrEnum):
    core = "core"
    released = "released"
    beta = "beta"
    early_access = "early_access"
    internal = "internal"
    deprecated = "deprecated"
    hidden = "hidden"


@dataclass(frozen=True)
class ModuleDefinition:
    id: str
    name: str
    description: str
    category: str
    release_state: ReleaseState
    default_enabled: bool
    introduced_version: str | None
    dependencies: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    route: str | None = None

    @property
    def household_toggleable(self) -> bool:
        return self.release_state in {
            ReleaseState.released,
            ReleaseState.beta,
            ReleaseState.early_access,
        }


MODULES: tuple[ModuleDefinition, ...] = (
    ModuleDefinition(
        "dashboard",
        "Dashboard",
        "The starting point for each Home.",
        "Core",
        ReleaseState.core,
        True,
        "0.1.0",
        permissions=("members.view",),
        route="/home",
    ),
    ModuleDefinition(
        "household_members",
        "Household members",
        "Profiles, relationships, invitations and permissions.",
        "Core",
        ReleaseState.core,
        True,
        "0.1.0",
        permissions=("members.view", "members.invite", "members.manage_relationships"),
        route="/people",
    ),
    ModuleDefinition(
        "security",
        "Security",
        "Authentication, sessions, recovery and audit protection.",
        "Core",
        ReleaseState.core,
        True,
        "0.1.0",
        route="/settings/security",
    ),
    ModuleDefinition(
        FeatureKey.calendar.value,
        "Calendar",
        "Shared household events, appointments and schedules.",
        "Family",
        ReleaseState.released,
        False,
        "0.1.0",
        dependencies=("household_members",),
        permissions=(
            "calendar.view",
            "calendar.create",
            "calendar.edit_own",
            "calendar.edit_all",
        ),
        route="/calendar",
    ),
    ModuleDefinition(
        FeatureKey.tasks.value,
        "Tasks",
        "Shared household tasks.",
        "Family",
        ReleaseState.hidden,
        False,
        None,
        dependencies=("household_members",),
        route="/tasks",
    ),
    ModuleDefinition(
        FeatureKey.shopping.value,
        "Shopping lists",
        "Collaborative household shopping lists.",
        "Family",
        ReleaseState.hidden,
        False,
        None,
        dependencies=("household_members",),
        route="/shopping",
    ),
    ModuleDefinition(
        FeatureKey.meals.value,
        "Meals",
        "Meal planning for the household.",
        "Home",
        ReleaseState.hidden,
        False,
        None,
        route="/meals",
    ),
    ModuleDefinition(
        FeatureKey.plans.value,
        "Plans",
        "Longer-term family plans.",
        "Family",
        ReleaseState.hidden,
        False,
        None,
        route="/plans",
    ),
    ModuleDefinition(
        FeatureKey.wish_lists.value,
        "Wish lists",
        "Gift ideas shared with selected people.",
        "Family",
        ReleaseState.hidden,
        False,
        None,
        dependencies=("household_members",),
        route="/wish-lists",
    ),
    ModuleDefinition(
        FeatureKey.notifications.value,
        "Notifications",
        "Push, email and in-app reminders — event reminders, daily briefings and "
        "household routines.",
        "Communication",
        ReleaseState.beta,
        False,
        "0.1.0",
        route="/notifications",
    ),
    ModuleDefinition(
        FeatureKey.external_sharing.value,
        "External sharing",
        "Share selected resources outside the Home.",
        "Experimental",
        ReleaseState.hidden,
        False,
        None,
        dependencies=("household_members",),
        permissions=("sharing.external",),
    ),
)

MODULE_BY_ID = {module.id: module for module in MODULES}


def module_definition(module_id: str) -> ModuleDefinition:
    return MODULE_BY_ID[module_id]


def household_modules() -> tuple[ModuleDefinition, ...]:
    return tuple(module for module in MODULES if module.release_state != ReleaseState.hidden)


def feature_modules() -> tuple[ModuleDefinition, ...]:
    return tuple(module for module in MODULES if module.id in {key.value for key in FeatureKey})
