"""Clock used by the library.

Call these functions on this module (``_timing.sleep``). Tests replace the
module attributes; binding them with ``from _timing import sleep`` would keep
the real clock.
"""

import random
import time


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def monotonic() -> float:
    return time.monotonic()


def jitter_fraction() -> float:
    """Uniform fraction in ``[0, 1)`` mixed into retry backoff."""
    return random.random()
