"""Thin wrapper around calling the (synchronous) Stripe SDK from async
FastAPI request handlers, plus error classification. Mirrors the
permanent/transient split mykhaya.mailer already uses for SMTP errors —
Stripe's own exception hierarchy (stripe.error.*) maps naturally onto the
same two buckets.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import stripe


class StripeUnavailableError(RuntimeError):
    """Transient — network/connection trouble or Stripe rate-limiting.
    Safe to ask the caller to retry; never treated as a definitive failure."""


class StripeRequestError(RuntimeError):
    """Permanent for this request — invalid parameters, an unknown/rejected
    object, or a misconfigured API key. Never retried automatically."""


async def call_stripe[T](func: Callable[[], T]) -> T:
    """Runs a blocking Stripe SDK call off the event loop (mykhaya.worker
    already uses the same asyncio.to_thread pattern for blocking SMTP/push
    calls) and translates stripe.error.* into the two buckets above. Never
    lets a raw Stripe exception (which may include request/response detail
    not meant for an API consumer) escape to a route handler unclassified.
    """
    try:
        return await asyncio.to_thread(func)
    except stripe.APIConnectionError as exc:
        raise StripeUnavailableError("Could not reach Stripe.") from exc
    except stripe.RateLimitError as exc:
        raise StripeUnavailableError("Stripe rate limit reached.") from exc
    except stripe.AuthenticationError as exc:
        # A configuration problem (bad secret key), not a per-request one —
        # still surfaced as "unavailable" to the caller since there's nothing
        # a customer can do about it; sanitised detail goes to the logger by
        # the route handler, never to the response body.
        raise StripeUnavailableError("Stripe billing is misconfigured.") from exc
    except stripe.InvalidRequestError as exc:
        raise StripeRequestError(str(exc.user_message or "Stripe rejected the request.")) from exc
    except stripe.CardError as exc:
        raise StripeRequestError(
            str(exc.user_message or "The payment method was declined.")
        ) from exc
    except stripe.StripeError as exc:
        raise StripeUnavailableError("Stripe returned an unexpected error.") from exc
