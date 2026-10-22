import pytest
import responses

from mailtm_client_wrapper import _timing


class FakeClock:
    """Clock whose sleep returns immediately and records each delay."""

    def __init__(self) -> None:
        self._now = 0.0
        self.delays: list[float] = []
        self.jitter = 0.0

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self._now += seconds

    def monotonic(self) -> float:
        return self._now

    def jitter_fraction(self) -> float:
        return self.jitter


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Replace the timing seam with an instant clock for this test."""
    clock = FakeClock()
    monkeypatch.setattr(_timing, "sleep", clock.sleep)
    monkeypatch.setattr(_timing, "monotonic", clock.monotonic)
    monkeypatch.setattr(_timing, "jitter_fraction", clock.jitter_fraction)
    return clock


@pytest.fixture(autouse=True)
def mocked_responses(request):
    """Active responses mock. Register stubs with ``mocked_responses.add(...)``.

    Tests marked ``live`` are left on the real network.
    """
    if request.node.get_closest_marker("live"):
        yield None
        return
    with responses.RequestsMock() as mock:
        yield mock
