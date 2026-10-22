import pytest
import responses

from fixtures import BASE_URL, TOKEN
from mailtm_client_wrapper import MailTMClient, _timing


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


@pytest.fixture(autouse=True)
def fake_clock(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> FakeClock:
    """Replace the timing seam with an instant clock.

    Live tests keep the real clock. Every other test records delays here so
    retries and later wait loops do not sleep for real.
    """
    clock = FakeClock()
    if request.node.get_closest_marker("live"):
        return clock
    monkeypatch.setattr(_timing, "sleep", clock.sleep)
    monkeypatch.setattr(_timing, "monotonic", clock.monotonic)
    monkeypatch.setattr(_timing, "jitter_fraction", clock.jitter_fraction)
    return clock


def _login(mocked_responses, client: MailTMClient) -> MailTMClient:
    mocked_responses.add(responses.POST, f"{BASE_URL}/token", json=TOKEN, status=200)
    client.login("user@example.com", "password")
    return client


@pytest.fixture
def authenticated_client(mocked_responses) -> MailTMClient:
    """A client that has already called login()."""
    return _login(mocked_responses, MailTMClient())


@pytest.fixture
def log_in(mocked_responses):
    """Log in a client, creating a default one when the test does not pass one."""

    def _log_in(client: MailTMClient | None = None) -> MailTMClient:
        return _login(mocked_responses, MailTMClient() if client is None else client)

    return _log_in


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
