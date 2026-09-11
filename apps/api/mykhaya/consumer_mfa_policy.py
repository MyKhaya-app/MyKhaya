"""Central consumer-browser MFA policy resolution.

Platform settings are the parent scope; Home and User rows may only make the
effective policy stricter or reduce the permitted method set.  Managed-child
authentication never calls this service.
"""

from dataclasses import dataclass
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import ConsumerMfaPolicy, Group, Membership, User

CONSUMER_MFA_POLICY_SETTING_KEY = "consumer_browser_mfa_policy"
MFA_METHODS = frozenset({"totp", "email"})


@dataclass(frozen=True)
class EffectiveConsumerMfaPolicy:
    configured_platform: str
    configured_user: str
    home_policies: tuple[tuple[uuid.UUID, str], ...]
    effective: str
    source: str
    allowed_methods: frozenset[str]
    enforcement_enabled: bool
    legacy_flag_fallback: bool

    @property
    def required(self) -> bool:
        return self.effective == ConsumerMfaPolicy.required.value


def _level(value: str) -> int:
    return 1 if value == ConsumerMfaPolicy.required.value else 0


def _normalise_methods(value: Any) -> frozenset[str]:
    if value is None:
        return MFA_METHODS
    if not isinstance(value, list):
        return frozenset()
    return frozenset(item for item in value if item in MFA_METHODS)


async def resolve_consumer_mfa_policy(
    db: AsyncSession, user_id: uuid.UUID, settings: Settings
) -> EffectiveConsumerMfaPolicy:
    from mykhaya.models import PlatformSetting

    platform_row = await db.scalar(
        select(PlatformSetting).where(PlatformSetting.key == CONSUMER_MFA_POLICY_SETTING_KEY)
    )
    platform_value = platform_row.value if platform_row else {}
    platform_policy = str(platform_value.get("policy", ConsumerMfaPolicy.optional.value))
    if platform_policy not in {"optional", "required"}:
        platform_policy = ConsumerMfaPolicy.optional.value
    methods = _normalise_methods(platform_value.get("allowed_methods"))

    memberships = (
        await db.execute(
            select(Group.id, Group.mfa_policy, Group.mfa_allowed_methods)
            .join(Membership, Membership.group_id == Group.id)
            .where(
                Membership.user_id == user_id,
                Membership.removed_at.is_(None),
                Group.is_active.is_(True),
            )
        )
    ).all()
    home_policies = tuple(
        (group_id, policy.value if isinstance(policy, ConsumerMfaPolicy) else str(policy))
        for group_id, policy, _ in memberships
    )
    for _, policy, home_methods in memberships:
        if home_methods is not None:
            methods &= _normalise_methods(home_methods)

    user = await db.get(User, user_id)
    user_policy = (
        user.mfa_policy.value
        if user is not None and isinstance(user.mfa_policy, ConsumerMfaPolicy)
        else ConsumerMfaPolicy.inherit.value
    )
    if user is not None and user.mfa_allowed_methods is not None:
        methods &= _normalise_methods(user.mfa_allowed_methods)

    effective = platform_policy
    source = "platform"
    if any(policy == ConsumerMfaPolicy.required.value for _, policy in home_policies):
        effective, source = ConsumerMfaPolicy.required.value, "home"
    if user_policy == ConsumerMfaPolicy.required.value:
        effective, source = ConsumerMfaPolicy.required.value, "user"

    legacy_fallback = settings.browser_mfa_handoff_enabled and platform_row is None
    if legacy_fallback:
        effective, source = ConsumerMfaPolicy.required.value, "rollout_flag"
    return EffectiveConsumerMfaPolicy(
        configured_platform=platform_policy,
        configured_user=user_policy,
        home_policies=home_policies,
        effective=effective,
        source=source,
        allowed_methods=methods,
        enforcement_enabled=settings.browser_mfa_handoff_enabled,
        legacy_flag_fallback=legacy_fallback,
    )


def policy_value(value: str) -> str:
    if value not in {"inherit", "optional", "required"}:
        raise ValueError("Invalid MFA policy value")
    return value


def methods_value(value: list[str]) -> list[str]:
    normalised = sorted(set(value))
    if not normalised or any(item not in MFA_METHODS for item in normalised):
        raise ValueError("At least one supported MFA method is required")
    return normalised
