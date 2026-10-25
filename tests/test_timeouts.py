"""Request timeouts are bounded, configurable, and reported as timeout errors."""

import pytest
import requests
import responses
import urllib3
from fixtures import (
    ACCOUNT,
    BASE_URL,
    DOMAIN_COLLECTION,
    MESSAGE_DETAIL,
    MESSAGE_LIST_ITEM,
    TOKEN,
    _recorded_timeout,
)

from mailtm_client_wrapper import (
    MailTMClient,
    MailTMConnectionError,
    MailTMTimeoutError,
    RetryPolicy,
)

INBOX = {
    "hydra:totalItems": 1,
    "hydra:member": [MESSAGE_LIST_ITEM],
}

NETWORK_CALLS = [
    ("get_domain", responses.GET, "/domains", DOMAIN_COLLECTION, (), False),
    (
        "create_account",
        responses.POST,
        "/accounts",
        ACCOUNT,
        ("user@example.com", "password"),
        False,
    ),
    ("login", responses.POST, "/token", TOKEN, ("user@example.com", "password"), False),
    ("read_inbox", responses.GET, "/messages", INBOX, (), True),
    (
        "read_message",
        responses.GET,
        "/messages/msg-1",
        MESSAGE_DETAIL,
        ("msg-1",),
        True,
    ),
    (
        "generate_random_credentials",
        responses.GET,
        "/domains",
        DOMAIN_COLLECTION,
        (),
        False,
    ),
]


_OMITTED = object()


def _call(client: MailTMClient, method_name: str, args: tuple, timeout=_OMITTED):
    method = getattr(client, method_name)
    if timeout is _OMITTED:
        return method(*args)
    return method(*args, timeout=timeout)


@pytest.mark.parametrize(
    ("method_name", "http_method", "path", "body", "args", "authenticated"),
    NETWORK_CALLS,
)
def test_network_calls_use_the_ten_second_default_timeout(
    mocked_responses,
    log_in,
    method_name,
    http_method,
    path,
    body,
    args,
    authenticated,
):
    """A client constructed without a timeout gives every network call 10 seconds."""
    client = MailTMClient()
    if authenticated:
        log_in(client)
    mocked_responses.add(http_method, f"{BASE_URL}{path}", json=body, status=200)

    getattr(client, method_name)(*args)

    assert _recorded_timeout(mocked_responses, path) == 10.0


@pytest.mark.parametrize(
    ("method_name", "http_method", "path", "body", "args", "authenticated"),
    NETWORK_CALLS,
)
def test_client_timeout_is_sent_on_every_network_call(
    mocked_responses,
    log_in,
    method_name,
    http_method,
    path,
    body,
    args,
    authenticated,
):
    """The timeout given to the client is the one every later call uses."""
    client = MailTMClient(timeout=4.5)
    if authenticated:
        log_in(client)
    mocked_responses.add(http_method, f"{BASE_URL}{path}", json=body, status=200)

    getattr(client, method_name)(*args)

    assert _recorded_timeout(mocked_responses, path) == 4.5


@pytest.mark.parametrize(
    ("method_name", "http_method", "path", "body", "args", "authenticated"),
    NETWORK_CALLS,
)
def test_per_call_timeout_overrides_only_that_call(
    mocked_responses,
    log_in,
    method_name,
    http_method,
    path,
    body,
    args,
    authenticated,
):
    """timeout= on one call replaces the client value; omitting it or passing None does not."""
    client = MailTMClient(timeout=4.5)
    if authenticated:
        log_in(client)
    for _ in range(3):
        mocked_responses.add(http_method, f"{BASE_URL}{path}", json=body, status=200)

    _call(client, method_name, args, timeout=8)
    assert _recorded_timeout(mocked_responses, path) == 8

    if method_name == "generate_random_credentials":
        client.domain = None
    _call(client, method_name, args)
    assert _recorded_timeout(mocked_responses, path) == 4.5

    if method_name == "generate_random_credentials":
        client.domain = None
    _call(client, method_name, args, timeout=None)
    assert _recorded_timeout(mocked_responses, path) == 4.5


def test_connect_and_read_pair_is_sent_unchanged(mocked_responses):
    """A (connect, read) pair reaches requests as the same value, on the client and on one call."""
    pair = (1.5, 20)
    client = MailTMClient(timeout=pair)
    mocked_responses.add(
        responses.GET, f"{BASE_URL}/domains", json=DOMAIN_COLLECTION, status=200
    )
    mocked_responses.add(
        responses.POST, f"{BASE_URL}/accounts", json=ACCOUNT, status=200
    )

    client.get_domain()
    client.create_account("user@example.com", "password")

    assert _recorded_timeout(mocked_responses, "/domains") is pair
    assert _recorded_timeout(mocked_responses, "/accounts") is pair

    override = (3, 9.0)
    mocked_responses.add(
        responses.GET, f"{BASE_URL}/domains", json=DOMAIN_COLLECTION, status=200
    )
    client.get_domain(timeout=override)

    assert _recorded_timeout(mocked_responses, "/domains") is override


INVALID_TIMEOUTS = [
    (0, ValueError),
    (0.0, ValueError),
    (-1, ValueError),
    (-0.5, ValueError),
    ("10", TypeError),
    (True, TypeError),
    (False, TypeError),
    ((0, 5), ValueError),
    ((5, 0.0), ValueError),
    ((-1, 5), ValueError),
    ((5, -0.1), ValueError),
    ((5, "1"), TypeError),
    ((None, 5), ValueError),
    ((True, 5), TypeError),
    ((), TypeError),
    ((1,), TypeError),
    ((1, 2, 3), TypeError),
    ([1.0, 2.0], TypeError),
    (float("inf"), ValueError),
    (float("-inf"), ValueError),
    (float("nan"), ValueError),
    ((float("inf"), 5), ValueError),
    ((5, float("nan")), ValueError),
    ((float("-inf"), 1), ValueError),
]


@pytest.mark.parametrize(
    ("timeout", "error_type"),
    [(None, ValueError), *INVALID_TIMEOUTS],
)
def test_invalid_timeout_is_rejected_when_the_client_is_constructed(timeout, error_type):
    """None, zero, negative and non-numeric timeouts cannot be stored on the client."""
    with pytest.raises(error_type, match="timeout"):
        MailTMClient(timeout=timeout)


@pytest.mark.parametrize(("timeout", "error_type"), INVALID_TIMEOUTS)
def test_invalid_timeout_is_rejected_before_get_domain_requests(
    mocked_responses, timeout, error_type
):
    """A bad per-call timeout is rejected before any request is sent."""
    with pytest.raises(error_type, match="timeout"):
        MailTMClient().get_domain(timeout=timeout)

    assert list(mocked_responses.calls) == []


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("get_domain", ()),
        ("create_account", ("user@example.com", "password")),
        ("login", ("user@example.com", "password")),
        ("read_inbox", ()),
        ("read_message", ("msg-1",)),
        ("generate_random_credentials", ()),
    ],
)
@pytest.mark.parametrize(
    ("timeout", "error_type"),
    [(0, ValueError), ("10", TypeError), ((1, -1), ValueError)],
)
def test_each_call_rejects_an_invalid_timeout_before_requesting(
    mocked_responses, method_name, args, timeout, error_type
):
    """Every network method rejects a bad timeout itself, and does not call the network."""
    with pytest.raises(error_type, match="timeout"):
        getattr(MailTMClient(), method_name)(*args, timeout=timeout)

    assert list(mocked_responses.calls) == []


@pytest.mark.parametrize(
    "transport_error",
    [requests.ReadTimeout("read timed out"), requests.ConnectTimeout("connect timed out")],
)
@pytest.mark.parametrize(
    ("method_name", "http_method", "path", "body", "args", "authenticated"),
    NETWORK_CALLS,
)
def test_read_and_connect_timeouts_name_the_operation_and_value(
    mocked_responses,
    log_in,
    transport_error,
    method_name,
    http_method,
    path,
    body,
    args,
    authenticated,
):
    """Both phases of a timeout raise one error naming the call and the allowed time."""
    client = MailTMClient(timeout=6.5)
    if authenticated:
        log_in(client)
    mocked_responses.add(http_method, f"{BASE_URL}{path}", body=transport_error)

    with pytest.raises(MailTMTimeoutError) as caught:
        getattr(client, method_name)(*args)

    assert f"{http_method} {path}" in str(caught.value)
    assert "timeout=6.5" in str(caught.value)
    assert caught.value.__cause__ is transport_error
    assert not isinstance(caught.value, MailTMConnectionError)


def test_timeout_error_names_the_per_call_value(mocked_responses):
    """The error reports the timeout that call used, not the client default."""
    transport_error = requests.ConnectTimeout("connect timed out")
    mocked_responses.add(responses.GET, f"{BASE_URL}/domains", body=transport_error)

    with pytest.raises(MailTMTimeoutError) as caught:
        MailTMClient(timeout=6.5).get_domain(timeout=(2, 30))

    assert "GET /domains" in str(caught.value)
    assert "timeout=(2, 30)" in str(caught.value)
    assert "6.5" not in str(caught.value)
    assert caught.value.__cause__ is transport_error


def _read_timeout_reported_as_connection_error(*, chained: bool) -> requests.ConnectionError:
    """Build the ConnectionError requests uses when a socket read times out mid-body."""
    read_timeout = urllib3.exceptions.ReadTimeoutError(None, "/domains", "Read timed out.")
    if chained:
        error = requests.ConnectionError("read timed out")
        error.__cause__ = read_timeout
        return error
    error = requests.ConnectionError(read_timeout)
    error.__context__ = read_timeout
    return error


@pytest.mark.parametrize("chained", [False, True])
def test_read_timeout_while_the_body_is_read_is_a_timeout_error(mocked_responses, chained):
    """A read timeout reported as ConnectionError is a timeout error, naming the call."""
    transport_error = _read_timeout_reported_as_connection_error(chained=chained)
    mocked_responses.add(responses.GET, f"{BASE_URL}/domains", body=transport_error)

    with pytest.raises(MailTMTimeoutError) as caught:
        MailTMClient(timeout=6.5, retry=RetryPolicy(max_attempts=1)).get_domain()

    assert type(caught.value) is MailTMTimeoutError
    assert not isinstance(caught.value, MailTMConnectionError)
    assert "GET /domains" in str(caught.value)
    assert "timeout=6.5" in str(caught.value)
    assert caught.value.__cause__ is transport_error


@pytest.mark.parametrize(
    "transport_error",
    [
        requests.ConnectionError("Failed to resolve 'api.mail.tm'"),
        requests.ConnectionError("Connection refused"),
        requests.ConnectionError("Connection reset by peer"),
    ],
)
def test_dns_refused_and_reset_stay_connection_errors(mocked_responses, transport_error):
    """A name lookup failure, a refusal, or a reset is a connection error, not a timeout."""
    mocked_responses.add(responses.GET, f"{BASE_URL}/domains", body=transport_error)

    with pytest.raises(MailTMConnectionError) as caught:
        MailTMClient().get_domain()

    assert not isinstance(caught.value, MailTMTimeoutError)
    assert caught.value.__cause__ is transport_error
