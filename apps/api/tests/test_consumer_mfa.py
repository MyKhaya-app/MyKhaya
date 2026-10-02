from types import SimpleNamespace
from uuid import uuid4

import pyotp
import pytest

from mykhaya import consumer_mfa
from mykhaya.secrets_crypto import decrypt_user_mfa_totp, encrypt_user_mfa_totp


def _settings():
    return SimpleNamespace(
        redis_url="redis://test",
        secret_key=SimpleNamespace(get_secret_value=lambda: "test-secret"),
    )


def test_totp_provisioning_and_clock_skew() -> None:
    secret = consumer_mfa.generate_totp_secret()
    uri = consumer_mfa.totp_provisioning_uri(secret, "person@example.com")
    assert uri.startswith("otpauth://totp/MyKhaya:")
    code = pyotp.TOTP(secret).now()
    assert consumer_mfa.matched_totp_step(secret, code) is not None
    assert consumer_mfa.matched_totp_step(secret, "00000") is None


def test_totp_secret_is_encrypted_and_round_trips() -> None:
    settings = _settings()
    secret = consumer_mfa.generate_totp_secret()
    ciphertext = encrypt_user_mfa_totp(settings, secret)
    assert ciphertext != secret
    assert secret not in ciphertext
    assert decrypt_user_mfa_totp(settings, ciphertext) == secret


def test_email_codes_are_six_digits_and_hashed() -> None:
    settings = _settings()
    code = consumer_mfa.new_email_code()
    assert len(code) == 6 and code.isdigit()
    assert consumer_mfa.hash_email_code(settings, code) != code
    assert consumer_mfa.hash_transaction(settings, str(uuid4()))


@pytest.mark.asyncio
async def test_totp_replay_claim_is_atomic(monkeypatch: pytest.MonkeyPatch) -> None:
    class Redis:
        claimed: set[str] = set()

        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return cls()

        async def set(self, key, _value, **kwargs):
            if kwargs.get("nx") and key in self.claimed:
                return False
            self.claimed.add(key)
            return True

        async def aclose(self):
            return None

    monkeypatch.setattr(consumer_mfa, "Redis", Redis)
    settings = _settings()
    user_id = uuid4()
    assert await consumer_mfa.claim_totp_step(settings, user_id, 1)
    assert not await consumer_mfa.claim_totp_step(settings, user_id, 1)
