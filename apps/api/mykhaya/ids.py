import secrets
import threading
import time
import uuid

_lock = threading.Lock()
_last_milliseconds = -1
_last_random_bits = 0


def uuid7() -> uuid.UUID:
    """Create an RFC 9562 UUIDv7 without requiring a database extension."""
    global _last_milliseconds, _last_random_bits
    with _lock:
        milliseconds = time.time_ns() // 1_000_000
        if milliseconds >= 1 << 48:
            raise OverflowError("timestamp exceeds UUIDv7 range")
        if milliseconds > _last_milliseconds:
            random_bits = secrets.randbits(74)
        else:
            milliseconds = _last_milliseconds
            random_bits = (_last_random_bits + 1) & ((1 << 74) - 1)
            if random_bits == 0:
                milliseconds += 1
        _last_milliseconds = milliseconds
        _last_random_bits = random_bits
    value = milliseconds << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)
    return uuid.UUID(int=value)
