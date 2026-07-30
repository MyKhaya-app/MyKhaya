import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    """Create an RFC 9562 UUIDv7 without requiring a database extension."""
    milliseconds = time.time_ns() // 1_000_000
    if milliseconds >= 1 << 48:
        raise OverflowError("timestamp exceeds UUIDv7 range")
    random_bits = secrets.randbits(74)
    value = milliseconds << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)
    return uuid.UUID(int=value)

