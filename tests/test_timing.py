import time

from mailtm_client_wrapper import _timing


def test_sleep_advances_the_clock_instantly_and_records_the_delay(fake_clock):
    """Sleeping through the timing seam moves the fake clock and keeps the delay."""
    before = _timing.monotonic()
    started = time.perf_counter()

    _timing.sleep(30)

    assert _timing.monotonic() == before + 30
    assert fake_clock.delays == [30]
    assert time.perf_counter() - started < 1


def test_fake_clock_keeps_jitter_fixed(fake_clock):
    """Retry tests can rely on one jitter fraction until they change it."""
    assert _timing.jitter_fraction() == 0.0

    fake_clock.jitter = 0.25

    assert _timing.jitter_fraction() == 0.25
