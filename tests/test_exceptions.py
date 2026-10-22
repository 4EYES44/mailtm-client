import pytest
import requests
import responses

from mailtm_client_wrapper import (
    MailTMAPIError,
    MailTMAuthError,
    MailTMClient,
    MailTMConnectionError,
    MailTMError,
    MailTMNotAuthenticatedError,
    MailTMRateLimitError,
    MailTMResponseError,
    MailTMServerError,
    MailTMTimeoutError,
    MailTMWaitTimeoutError,
)
from fixtures import ERROR_401, ERROR_404, ERROR_422, TOKEN

BASE_URL = "https://api.mail.tm"


def test_library_errors_share_one_root_and_keep_their_branches():
    """Every library failure is one of the documented branches, and a wait deadline is not a request timeout."""
    assert issubclass(MailTMTimeoutError, MailTMError)
    assert issubclass(MailTMConnectionError, MailTMError)
    assert issubclass(MailTMAPIError, MailTMError)
    assert issubclass(MailTMAuthError, MailTMAPIError)
    assert issubclass(MailTMNotAuthenticatedError, MailTMAuthError)
    assert issubclass(MailTMRateLimitError, MailTMAPIError)
    assert issubclass(MailTMServerError, MailTMAPIError)
    assert issubclass(MailTMResponseError, MailTMError)
    assert not issubclass(MailTMResponseError, MailTMAPIError)
    assert issubclass(MailTMWaitTimeoutError, MailTMError)
    assert not issubclass(MailTMWaitTimeoutError, MailTMTimeoutError)
    assert not issubclass(MailTMTimeoutError, TimeoutError)
    assert not issubclass(MailTMConnectionError, ConnectionError)

    deadline = MailTMWaitTimeoutError("no message arrived", timeout=60.0)

    assert not isinstance(deadline, MailTMTimeoutError)
    assert deadline.timeout == 60.0


OPERATIONS = [
    ("get_domain", responses.GET, "/domains", (), False),
    ("create_account", responses.POST, "/accounts", ("user@example.com", "password"), False),
    ("login", responses.POST, "/token", ("user@example.com", "password"), False),
    ("read_inbox", responses.GET, "/messages", (), True),
    ("read_message", responses.GET, "/messages/msg-1", ("msg-1",), True),
]

STATUS_ERRORS = [
    (401, ERROR_401, MailTMAuthError),
    (429, {"message": "Too many requests"}, MailTMRateLimitError),
    (500, {"message": "Error"}, MailTMServerError),
    (422, ERROR_422, MailTMAPIError),
    (404, ERROR_404, MailTMAPIError),
]


def _client(mocked_responses, *, authenticated: bool) -> MailTMClient:
    client = MailTMClient()
    if authenticated:
        mocked_responses.add(responses.POST, f"{BASE_URL}/token", json=TOKEN, status=200)
        client.login("user@example.com", "password")
    return client


@pytest.mark.parametrize(
    ("method_name", "http_method", "path", "args", "authenticated"),
    OPERATIONS,
)
@pytest.mark.parametrize(("status", "body", "error_type"), STATUS_ERRORS)
def test_each_call_maps_http_status_to_its_error(
    mocked_responses,
    method_name,
    http_method,
    path,
    args,
    authenticated,
    status,
    body,
    error_type,
):
    """401, 429, 5xx and other 4xx on every call keep their class, status and body."""
    client = _client(mocked_responses, authenticated=authenticated)
    mocked_responses.add(http_method, f"{BASE_URL}{path}", json=body, status=status)

    with pytest.raises(error_type) as caught:
        getattr(client, method_name)(*args)

    error = caught.value
    assert type(error) is error_type
    assert error.status_code == status
    assert error.body == body
    assert isinstance(error.__cause__, requests.HTTPError)
    if error_type is MailTMRateLimitError:
        assert error.retry_after is None


@pytest.mark.parametrize(
    ("method_name", "http_method", "path", "args", "authenticated"),
    OPERATIONS,
)
@pytest.mark.parametrize("raw_body", ["not-json", "", "[]", "null"])
def test_success_status_with_unusable_body_raises_response_error(
    mocked_responses,
    method_name,
    http_method,
    path,
    args,
    authenticated,
    raw_body,
):
    """A 2xx body that is not a JSON object is a response error, not an API error."""
    client = _client(mocked_responses, authenticated=authenticated)
    mocked_responses.add(
        http_method,
        f"{BASE_URL}{path}",
        body=raw_body,
        status=200,
        content_type="application/json",
    )

    with pytest.raises(MailTMResponseError) as caught:
        getattr(client, method_name)(*args)

    error = caught.value
    assert not isinstance(error, MailTMAPIError)
    assert error.status_code == 200
    if raw_body in ("not-json", ""):
        assert error.body == raw_body
        assert isinstance(error.__cause__, requests.JSONDecodeError)
    else:
        assert error.__cause__ is None


TRANSPORT_FAILURES = [
    (requests.ReadTimeout("read timed out"), MailTMTimeoutError),
    (requests.ConnectTimeout("connect timed out"), MailTMTimeoutError),
    (requests.ConnectionError("connection refused"), MailTMConnectionError),
]


@pytest.mark.parametrize(
    ("method_name", "http_method", "path", "args", "authenticated"),
    OPERATIONS,
)
@pytest.mark.parametrize(("transport_error", "error_type"), TRANSPORT_FAILURES)
def test_transport_failures_keep_the_requests_cause(
    mocked_responses,
    method_name,
    http_method,
    path,
    args,
    authenticated,
    transport_error,
    error_type,
):
    """A timeout or dropped connection is its own error, chained to the requests exception."""
    client = _client(mocked_responses, authenticated=authenticated)
    mocked_responses.add(http_method, f"{BASE_URL}{path}", body=transport_error)

    with pytest.raises(error_type) as caught:
        getattr(client, method_name)(*args)

    assert type(caught.value) is error_type
    assert caught.value.__cause__ is transport_error


@pytest.mark.parametrize(
    ("method_name", "http_method", "path", "args", "authenticated"),
    OPERATIONS,
)
@pytest.mark.parametrize(
    ("header", "retry_after"),
    [
        ("12", 12),
        ("1.5", 1.5),
        ("Wed, 21 Oct 2015 07:28:00 GMT", None),
    ],
)
def test_rate_limit_records_a_numeric_retry_after(
    mocked_responses,
    method_name,
    http_method,
    path,
    args,
    authenticated,
    header,
    retry_after,
):
    """A 429 keeps a numeric Retry-After and ignores a non-numeric one."""
    client = _client(mocked_responses, authenticated=authenticated)
    mocked_responses.add(
        http_method,
        f"{BASE_URL}{path}",
        json={"message": "Too many requests"},
        status=429,
        headers={"Retry-After": header},
    )

    with pytest.raises(MailTMRateLimitError) as caught:
        getattr(client, method_name)(*args)

    assert caught.value.retry_after == retry_after
    assert caught.value.status_code == 429


@pytest.mark.parametrize(
    ("method_name", "args"),
    [("read_inbox", ()), ("read_message", ("msg-1",))],
)
def test_inbox_and_message_before_login_make_no_request(
    mocked_responses, method_name, args
):
    """Calling an authenticated method with no token explains that login() is required."""
    with pytest.raises(MailTMNotAuthenticatedError, match=r"login\(\)") as caught:
        getattr(MailTMClient(), method_name)(*args)

    assert list(mocked_responses.calls) == []
    assert isinstance(caught.value, MailTMAuthError)
    assert caught.value.status_code is None


def test_non_json_error_status_stays_an_api_error(mocked_responses):
    """A non-JSON 4xx is still an API error; only a bad 2xx body is a response error."""
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/domains",
        body="nope",
        status=401,
        content_type="text/plain",
    )

    with pytest.raises(MailTMAuthError) as caught:
        MailTMClient().get_domain()

    assert caught.value.status_code == 401
    assert caught.value.body == "nope"
    assert isinstance(caught.value.__cause__, requests.HTTPError)


def test_empty_domain_list_is_a_response_error(mocked_responses):
    """An empty domain collection fails instead of raising a bare Exception."""
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/domains",
        json={"hydra:totalItems": 0, "hydra:member": []},
        status=200,
    )

    with pytest.raises(MailTMResponseError) as caught:
        MailTMClient().get_domain()

    assert not isinstance(caught.value, MailTMAPIError)


OTHER_REQUEST_FAILURES = [
    (requests.exceptions.ChunkedEncodingError, MailTMConnectionError, 3),
    (requests.exceptions.ContentDecodingError, MailTMResponseError, 1),
    (requests.exceptions.TooManyRedirects, MailTMError, 1),
    (requests.exceptions.InvalidURL, MailTMError, 1),
    (requests.exceptions.InvalidHeader, MailTMError, 1),
    (requests.exceptions.MissingSchema, MailTMError, 1),
    (requests.exceptions.InvalidSchema, MailTMError, 1),
    (requests.exceptions.URLRequired, MailTMError, 1),
    (requests.exceptions.RetryError, MailTMError, 1),
    (requests.exceptions.UnrewindableBodyError, MailTMError, 1),
]


@pytest.mark.parametrize(("requests_error", "error_type", "attempts"), OTHER_REQUEST_FAILURES)
def test_other_requests_failures_are_library_errors_and_only_a_broken_body_is_retried(
    fake_clock, mocked_responses, requests_error, error_type, attempts
):
    """A requests failure other than a timeout or a dropped connection is still a library error.

    A body cut off mid-transfer is a connection error and is tried again. A bad URL,
    a redirect loop, a body that cannot be decoded, and any other request failure
    are raised once, with the requests error chained.
    """
    fake_clock.jitter = 0.0
    for _ in range(attempts):
        mocked_responses.add(
            responses.GET,
            f"{BASE_URL}/domains",
            body=requests_error("request failed"),
        )

    with pytest.raises(error_type) as caught:
        MailTMClient().get_domain()

    error = caught.value
    assert type(error) is error_type
    assert isinstance(error.__cause__, requests_error)
    assert len(mocked_responses.calls) == attempts
    assert fake_clock.delays == ([1.0, 2.0] if attempts == 3 else [])


def test_login_without_a_token_is_a_response_error(mocked_responses):
    """A 2xx login body with no token is a response error, not a bare Exception."""
    mocked_responses.add(
        responses.POST,
        f"{BASE_URL}/token",
        json={"id": "abc"},
        status=200,
    )

    with pytest.raises(MailTMResponseError, match="token") as caught:
        MailTMClient().login("user@example.com", "password")

    assert caught.value.body == {"id": "abc"}
