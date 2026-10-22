"""Transient failures are retried with backoff; permanent failures are not."""

import pytest
import requests
import responses

from fixtures import (
    ACCOUNT,
    DOMAIN_COLLECTION,
    ERROR_401,
    ERROR_422,
    MESSAGE_DETAIL,
    MESSAGE_LIST_ITEM,
    TOKEN,
)
from mailtm_client_wrapper import (
    MailTMAPIError,
    MailTMAuthError,
    MailTMClient,
    MailTMConnectionError,
    MailTMRateLimitError,
    MailTMResponseError,
    MailTMServerError,
    MailTMTimeoutError,
    RetryPolicy,
)

BASE_URL = "https://api.mail.tm"


def test_rate_limit_then_success_sleeps_once_for_the_backoff_delay(
    fake_clock, mocked_responses
):
    """A 429 followed by a domain succeeds after one delay of base plus the fixed jitter."""
    fake_clock.jitter = 0.5
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/domains",
        json={"message": "Too many requests"},
        status=429,
    )
    mocked_responses.add(
        responses.GET, f"{BASE_URL}/domains", json=DOMAIN_COLLECTION, status=200
    )

    domain = MailTMClient().get_domain()

    assert domain == "example.com"
    assert fake_clock.delays == [1.125]


def test_repeated_server_failures_raise_the_last_error_after_capped_backoff(
    fake_clock, mocked_responses
):
    """Three 5xx responses raise the last one after two delays that double up to the cap."""
    fake_clock.jitter = 0.0
    client = MailTMClient(
        retry=RetryPolicy(max_attempts=3, base_delay=4.0, max_delay=6.0)
    )
    for status in (500, 502, 503):
        mocked_responses.add(
            responses.GET,
            f"{BASE_URL}/domains",
            json={"status": status},
            status=status,
        )

    with pytest.raises(MailTMServerError) as caught:
        client.get_domain()

    error = caught.value
    assert type(error) is MailTMServerError
    assert error.status_code == 503
    assert error.body == {"status": 503}
    assert isinstance(error.__cause__, requests.HTTPError)
    assert fake_clock.delays == [4.0, 6.0]


INBOX = {"hydra:totalItems": 1, "hydra:member": [MESSAGE_LIST_ITEM]}

RETRYING_CALLS = [
    ("get_domain", responses.GET, "/domains", (), False),
    ("login", responses.POST, "/token", ("user@example.com", "password"), False),
    ("read_inbox", responses.GET, "/messages", (), True),
    ("read_message", responses.GET, "/messages/msg-1", ("msg-1",), True),
]

SUCCESS = {
    "get_domain": (DOMAIN_COLLECTION, "example.com"),
    "login": (TOKEN, "documented-token"),
    "read_inbox": (INBOX, [MESSAGE_LIST_ITEM]),
    "read_message": (MESSAGE_DETAIL, MESSAGE_DETAIL),
}


def _client(mocked_responses, *, authenticated: bool) -> MailTMClient:
    client = MailTMClient()
    if authenticated:
        mocked_responses.add(responses.POST, f"{BASE_URL}/token", json=TOKEN, status=200)
        client.login("user@example.com", "password")
    return client


def _calls_for(mocked_responses, path: str) -> list:
    url = f"{BASE_URL}{path}"
    return [
        call
        for call in mocked_responses.calls
        if call.request.url == url or call.request.url.startswith(f"{url}?")
    ]


def _add_failure(mocked_responses, http_method: str, path: str, failure: str) -> None:
    url = f"{BASE_URL}{path}"
    if failure == "timeout":
        mocked_responses.add(http_method, url, body=requests.ReadTimeout("read timed out"))
        return
    if failure == "connection":
        mocked_responses.add(
            http_method, url, body=requests.ConnectionError("connection refused")
        )
        return
    mocked_responses.add(http_method, url, json={"message": failure}, status=int(failure))


@pytest.mark.parametrize(
    ("method_name", "http_method", "path", "args", "authenticated"),
    RETRYING_CALLS,
)
@pytest.mark.parametrize("failure", ["timeout", "connection", "429", "500"])
def test_transient_failure_is_retried_and_then_succeeds(
    fake_clock,
    mocked_responses,
    method_name,
    http_method,
    path,
    args,
    authenticated,
    failure,
):
    """Timeouts, connection errors, 429 and 5xx are tried again and can then succeed."""
    fake_clock.jitter = 0.0
    body, expected = SUCCESS[method_name]
    client = _client(mocked_responses, authenticated=authenticated)
    _add_failure(mocked_responses, http_method, path, failure)
    mocked_responses.add(http_method, f"{BASE_URL}{path}", json=body, status=200)

    assert getattr(client, method_name)(*args) == expected
    assert len(_calls_for(mocked_responses, path)) == 2
    assert fake_clock.delays == [1.0]


PERMANENT_FAILURES = [
    (401, ERROR_401, MailTMAuthError),
    (422, ERROR_422, MailTMAPIError),
    (200, "not-json", MailTMResponseError),
]


@pytest.mark.parametrize(
    ("method_name", "http_method", "path", "args", "authenticated"),
    RETRYING_CALLS,
)
@pytest.mark.parametrize(("status", "payload", "error_type"), PERMANENT_FAILURES)
def test_auth_client_and_response_errors_are_not_retried(
    fake_clock,
    mocked_responses,
    method_name,
    http_method,
    path,
    args,
    authenticated,
    status,
    payload,
    error_type,
):
    """401, other 4xx and a bad 2xx body fail on the first request without sleeping."""
    client = _client(mocked_responses, authenticated=authenticated)
    url = f"{BASE_URL}{path}"
    if status == 200:
        mocked_responses.add(
            http_method, url, body=payload, status=200, content_type="application/json"
        )
    else:
        mocked_responses.add(http_method, url, json=payload, status=status)

    with pytest.raises(error_type) as caught:
        getattr(client, method_name)(*args)

    assert type(caught.value) is error_type
    assert len(_calls_for(mocked_responses, path)) == 1
    assert fake_clock.delays == []


def test_account_creation_retries_a_rate_limit(fake_clock, mocked_responses):
    """Creating an account tries again after 429 and then returns success."""
    fake_clock.jitter = 0.0
    _add_failure(mocked_responses, responses.POST, "/accounts", "429")
    mocked_responses.add(
        responses.POST, f"{BASE_URL}/accounts", json=ACCOUNT, status=200
    )

    created = MailTMClient().create_account("user@example.com", "password")

    assert created is True
    assert len(_calls_for(mocked_responses, "/accounts")) == 2
    assert fake_clock.delays == [1.0]


@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        ("timeout", MailTMTimeoutError),
        ("connection", MailTMConnectionError),
        ("500", MailTMServerError),
    ],
)
def test_account_creation_does_not_retry_transport_or_server_errors(
    fake_clock, mocked_responses, failure, error_type
):
    """A timeout, dropped connection or 5xx while creating an account is not tried again."""
    _add_failure(mocked_responses, responses.POST, "/accounts", failure)

    with pytest.raises(error_type):
        MailTMClient().create_account("user@example.com", "password")

    assert len(_calls_for(mocked_responses, "/accounts")) == 1
    assert fake_clock.delays == []


def test_account_creation_keeps_a_server_error_when_retry_after_exceeds_the_cap(
    fake_clock, mocked_responses
):
    """A long Retry-After on a 503 does not retry account creation or change the error."""
    mocked_responses.add(
        responses.POST,
        f"{BASE_URL}/accounts",
        json={"message": "unavailable"},
        status=503,
        headers={"Retry-After": "30"},
    )

    with pytest.raises(MailTMServerError) as caught:
        MailTMClient().create_account("user@example.com", "password")

    assert type(caught.value) is MailTMServerError
    assert caught.value.status_code == 503
    assert len(_calls_for(mocked_responses, "/accounts")) == 1
    assert fake_clock.delays == []


HTTP_DATE = "Wed, 21 Oct 2015 07:28:00 GMT"


@pytest.mark.parametrize("status", [429, 503])
def test_short_retry_after_replaces_the_backoff_delay(
    fake_clock, mocked_responses, status
):
    """A numeric Retry-After within the cap is the whole wait, on 429 and on 503."""
    fake_clock.jitter = 1.0
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/domains",
        json={"message": "later"},
        status=status,
        headers={"Retry-After": "1.5"},
    )
    mocked_responses.add(
        responses.GET, f"{BASE_URL}/domains", json=DOMAIN_COLLECTION, status=200
    )

    assert MailTMClient().get_domain() == "example.com"
    assert fake_clock.delays == [1.5]


@pytest.mark.parametrize("status", [429, 503])
def test_retry_after_above_the_cap_fails_immediately(
    fake_clock, mocked_responses, status
):
    """A Retry-After longer than the cap raises a rate-limit error and does not sleep."""
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/domains",
        json={"message": "later"},
        status=status,
        headers={"Retry-After": "30"},
    )

    with pytest.raises(MailTMRateLimitError) as caught:
        MailTMClient().get_domain()

    error = caught.value
    assert type(error) is MailTMRateLimitError
    assert error.retry_after == 30
    assert error.status_code == status
    assert len(_calls_for(mocked_responses, "/domains")) == 1
    assert fake_clock.delays == []


@pytest.mark.parametrize("status", [429, 503])
def test_http_date_retry_after_is_ignored(fake_clock, mocked_responses, status):
    """An HTTP-date Retry-After falls back to the normal backoff delay."""
    fake_clock.jitter = 0.5
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/domains",
        json={"message": "later"},
        status=status,
        headers={"Retry-After": HTTP_DATE},
    )
    mocked_responses.add(
        responses.GET, f"{BASE_URL}/domains", json=DOMAIN_COLLECTION, status=200
    )

    assert MailTMClient().get_domain() == "example.com"
    assert fake_clock.delays == [1.125]


def test_single_attempt_policy_does_not_retry(fake_clock, mocked_responses):
    """RetryPolicy(max_attempts=1) fails on the first response and does not sleep."""
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/domains",
        json={"message": "Too many requests"},
        status=429,
    )

    with pytest.raises(MailTMRateLimitError):
        MailTMClient(retry=RetryPolicy(max_attempts=1)).get_domain()

    assert len(_calls_for(mocked_responses, "/domains")) == 1
    assert fake_clock.delays == []


def test_each_attempt_is_sent_with_the_same_timeout(mocked_responses):
    """The timeout chosen for a call is the one every attempt hands to requests."""
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/domains",
        body=requests.ReadTimeout("read timed out"),
    )

    with pytest.raises(MailTMTimeoutError):
        MailTMClient(timeout=10.0).get_domain(timeout=2.5)

    assert [
        call.request.req_kwargs["timeout"] for call in mocked_responses.calls
    ] == [2.5, 2.5, 2.5]


@pytest.mark.parametrize(("jitter", "delay"), [(0.0, 1.0), (1.0, 1.25)])
def test_jitter_adds_delay_and_never_shortens_the_backoff(
    fake_clock, mocked_responses, jitter, delay
):
    """Jitter is a fraction of the backoff added on top, so the wait stays at least the base."""
    fake_clock.jitter = jitter
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/domains",
        json={"message": "Too many requests"},
        status=429,
    )
    mocked_responses.add(
        responses.GET, f"{BASE_URL}/domains", json=DOMAIN_COLLECTION, status=200
    )

    assert MailTMClient().get_domain() == "example.com"
    assert fake_clock.delays == [delay]
