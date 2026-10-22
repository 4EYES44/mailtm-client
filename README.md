# mailtm-client-wrapper

Synchronous client for the [Mail.tm](https://docs.mail.tm/) HTTP API. It looks up a domain, creates an account, logs in, reads the inbox, waits until a message arrives, and copies the text between two markers out of the body.

The import package is `mailtm_client_wrapper`. Python 3.12 or newer is required (`requires-python` is `>=3.12`, with no upper bound).

## Installation

Clone the repository and install it, including the dev dependency group (`pytest` and `responses`):

```bash
git clone https://github.com/4EYES44/mailtm-client.git
cd mailtm-client
uv sync
```

`uv sync` creates `.venv` and installs this package. Run the examples and the tests with `uv run` so that environment is used. The library talks to Mail.tm through `requests`.

## Quick start

```python
from mailtm_client_wrapper import MailTMClient

client = MailTMClient()
email, password = client.generate_random_credentials()
client.create_account(email, password)
token = client.login(email, password)
for summary in client.read_inbox():
    print(summary["id"], summary["subject"])
```

`create_account` returns `True`. `login` returns the `token` value from the response and stores it on the client. `read_inbox` returns a list of message dicts.

## Client

```text
MailTMClient(base_url="https://api.mail.tm", *, timeout=10.0, retry=None)
```

`timeout` and `retry` are keyword-only. `base_url` is joined in front of paths such as `/domains` and `/messages`; the default has no trailing slash.

`timeout` is the per-request timeout passed to `requests`. A single number applies to connect and to each socket read. A pair is `(connect, read)` and is passed through unchanged. The default is `10.0` seconds. On a method, `timeout=None` means "use the client value". On the constructor, `None` is rejected.

These values raise `ValueError`: `None` on the constructor, zero, a negative number, or a pair that contains one of those. These values raise `TypeError`: a bool, a string, a list, a pair of the wrong length, or a pair that contains a bool or a non-number. The same rules apply to a per-call `timeout`, except that omitting it or passing `None` keeps the client value. The invalid value is rejected before any request is sent.

Omitting `retry`, or passing `None`, uses a default `RetryPolicy()`. See [Retries](#retries).

After construction:

| Attribute | Value |
| --- | --- |
| `base_url` | The base URL passed in |
| `session` | The `requests.Session` used for every call |
| `token` | `None` until `login`, then the token that was stored |
| `domain` | `None` until `get_domain` stores one |

`login` sets `session`'s `Authorization` header to `Bearer <token>`. `email_address` and `password` stay `None`; none of the methods assign them.

## Methods

The blocks in this section are signatures. Each method accepts `timeout=` as a keyword of type `int | float | tuple[int | float, int | float] | None`. That argument is the request timeout described above, except on `wait_for_message`, whose `timeout` is the wait deadline (`int | float`, default `60.0`).

### `get_domain`

```text
get_domain(*, timeout=None) -> str
```

`GET /domains`. Reads the first page only. Returns the `domain` of the first member that is a JSON object with boolean `isActive` true and boolean `isPrivate` false, and stores it on `client.domain`. If that member has no `domain` key, `MailTMResponseError` is raised and later members are not considered. If no member qualifies, including when `hydra:member` is an empty list, raises `MailTMResponseError`.

### `create_account`

```text
create_account(email_address, password, *, timeout=None) -> bool
```

`POST /accounts` with JSON `{"address": email_address, "password": password}`. Returns `True` when the response is a 2xx JSON object. This method retries only HTTP 429. A timeout, a connection error, or a 5xx is raised on the first attempt, because the account may already exist.

### `login`

```text
login(email_address, password, *, timeout=None) -> str
```

`POST /token` with JSON `{"address": email_address, "password": password}`. Requires a `token` key. Returns that value, stores it on `client.token`, and sends it as a bearer token on later requests.

### `generate_random_credentials`

```text
generate_random_credentials(*, timeout=None) -> tuple[str, str]
```

Returns `(email, password)`. The local part is 10 characters from `a-z` and `0-9`. The password is 12 characters from `a-z`, `A-Z`, and `0-9`. Characters come from `secrets`. If `client.domain` is already set, no request is made. Otherwise the domain comes from `get_domain`, using the same request timeout. The address and password are not stored on the client.

### `read_inbox`

```text
read_inbox(*, timeout=None) -> list[MessageSummary]
```

`GET /messages` for page 1, then 2, and so on, until one of these is true:

- `hydra:member` is an empty list
- the page contains no message `id` that is not already in the result
- `hydra:totalItems` is a non-negative integer (a boolean does not count) and the number of collected messages has reached it

The result is one list, in the order the server sent, with duplicate ids removed. The return value is the dicts from the API. The annotation is `list[MessageSummary]`; nothing is converted into a class.

Each page is a separate HTTP call. Every page uses the timeout chosen for this `read_inbox` call and gets its own retry attempts. If a page fails after retries, that error is raised and the method does not return the pages already read. A missing `hydra:member`, a `hydra:member` that is not a list, or a message that is not an object or lacks a required key raises `MailTMResponseError`. An inbox whose first page has an empty `hydra:member` returns `[]`.

`read_inbox` requires `login` first.

### `read_message`

```text
read_message(message_id, *, timeout=None) -> Message
```

`GET /messages/{message_id}`. Returns the JSON object. `text` and `html` are required, so a body that omits either key raises `MailTMResponseError`. Requires `login` first.

### `wait_for_message`

```text
wait_for_message(predicate=None, *, timeout=60.0, poll_interval=3.0, exclude_ids=()) -> Message
```

Polls `read_inbox` until one summary is accepted, then returns `read_message` for that id. There is no separate request-timeout argument: each poll uses the client request timeout and the client retry policy.

`predicate` is called with each inbox summary. A false result skips that summary. `None` accepts any summary. Messages already in the inbox are candidates. `exclude_ids` skips summaries whose `id` is in that collection, so a later wait can ignore messages already seen. The default excludes nothing.

The first poll is immediate. After a poll, if the deadline is still ahead, the helper sleeps for the smaller of `poll_interval` and the time remaining, then polls again. That last poll is how a message that arrives at the deadline is still returned. If the deadline has passed and nothing matched, it raises `MailTMWaitTimeoutError`. The exception attribute `timeout` is this wait deadline, not the request timeout. The message is `No matching message arrived within {timeout} seconds`.

`timeout` and `poll_interval` must be positive numbers. `None`, zero, and negative numbers raise `ValueError`. Bools and other non-numbers raise `TypeError`. Those checks happen before any poll.

Any other `MailTMError` from a poll, after that call's own retries, propagates immediately. Calling this before `login` raises `MailTMNotAuthenticatedError` and does not send a request.

The deadline is checked only between polls. It is not checked between inbox pages, and request timeouts are not shortened to the time remaining. During an outage the in-flight HTTP call can run past the deadline by that call's retry budget. With the defaults that is about 33 seconds: three 10-second attempts, plus backoff of 1 second and 2 seconds, plus up to 25% jitter on those two sleeps. A poll that succeeds can also run past the deadline while it finishes the remaining pages and, on a match, `read_message`.

```python
from mailtm_client_wrapper import MailTMWaitTimeoutError, extract_between

seen = [summary["id"] for summary in client.read_inbox()]
try:
    message = client.wait_for_message(exclude_ids=seen)
except MailTMWaitTimeoutError as exc:
    raise SystemExit(f"no message within {exc.timeout} seconds") from exc

code = extract_between(message["text"], "the email : ", " , dont")
```

This continues from the logged-in client in [Quick start](#quick-start). For a message whose `text` is `hello , this is the otp for the email : 1234 , dont share it with anyone`, `code` is `"1234"`. If either marker is missing, or the span is empty after trimming, `code` is `None`.

A predicate sees the summary only (`subject` is required; `intro` is optional). It does not receive `text` or `html`. Using the same `client` and `seen`:

```python
client.wait_for_message(
    lambda summary: summary["subject"] == "Your code",
    timeout=60,
    poll_interval=3,
    exclude_ids=seen,
)
```

## Retries

```text
RetryPolicy(max_attempts=3, base_delay=1.0, max_delay=8.0)
```

`RetryPolicy` is a frozen dataclass. `max_attempts` is the total number of attempts, including the first. `RetryPolicy(max_attempts=1)` turns retries off. Pass the policy to the client; there is no per-call retry argument.

```python
from mailtm_client_wrapper import MailTMClient, RetryPolicy

MailTMClient(retry=RetryPolicy(max_attempts=1))
MailTMClient(
    timeout=(3.0, 30.0),
    retry=RetryPolicy(max_attempts=5, base_delay=0.5, max_delay=8.0),
)
```

`get_domain`, `login`, `read_inbox`, and `read_message` retry `MailTMRateLimitError` (429), `MailTMServerError` (any 5xx), `MailTMTimeoutError`, and `MailTMConnectionError`. They do not retry `MailTMAuthError`, `MailTMResponseError`, or any other 4xx (`MailTMAPIError`, including 404 and 422). `create_account` retries only 429.

The request timeout applies to each attempt. When the attempts are used up, the last error is raised unchanged, with its original type.

After failed attempt `n` (1 for the first failure), if another attempt remains and no `Retry-After` override applies, the sleep is `min(max_delay, base_delay * 2 ** (n - 1))`, plus up to 25% of that delay. The extra fraction is uniform in `[0, 1)` and is only added. With the defaults the sleeps are 1 second and then 2 seconds, each plus that jitter. The third attempt is the last, so there is no third sleep.

On HTTP 429 and 503, a numeric `Retry-After` (seconds) replaces that sleep when it is less than or equal to `max_delay`. No jitter is added on top. When it is greater than `max_delay`, the client does not sleep. If another attempt is still allowed, that 429 or 503 raises `MailTMRateLimitError` immediately: `retry_after` is the header value, and a 503 keeps `status_code` 503. If the failure is already the last attempt, the original error is raised (`MailTMRateLimitError` for 429, `MailTMServerError` for 503). `create_account` does not retry 503, so a long `Retry-After` on account creation stays `MailTMServerError`. A non-numeric `Retry-After`, including an HTTP date, is ignored and the backoff above is used. `retry_after` on the exception is `None` when the header is absent or not numeric.

## `extract_between`

```text
extract_between(text, start, end) -> str | None
```

Exported from `mailtm_client_wrapper`. It makes no HTTP request and `wait_for_message` does not call it.

The markers are literal and case-sensitive. The first `start` is found, then the first `end` after that start. The span between them is returned with leading and trailing whitespace stripped. If either marker is absent, or the stripped span is empty, the result is `None`. An empty marker raises `ValueError`. A non-string `text`, `start`, or `end` raises `TypeError`.

```python
from mailtm_client_wrapper import extract_between

body = "hello , this is the otp for the email : 1234 , dont share it with anyone"
code = extract_between(body, "the email : ", " , dont")
```

`code` is `"1234"`. Pass `message["text"]`, or any other string, such as `html` fragments you have already joined.

## Exceptions

Every failure this library raises is a `MailTMError`. They do not subclass the builtin `TimeoutError` or `ConnectionError`. Import them from `mailtm_client_wrapper`.

```text
MailTMError
├── MailTMTimeoutError
├── MailTMConnectionError
├── MailTMAPIError                  status_code, body
│   ├── MailTMAuthError
│   │   └── MailTMNotAuthenticatedError
│   ├── MailTMRateLimitError        retry_after
│   └── MailTMServerError
├── MailTMResponseError             status_code, body
└── MailTMWaitTimeoutError          timeout
```

| Situation | Exception |
| --- | --- |
| Connect or read timeout | `MailTMTimeoutError` |
| DNS failure, connection refused, connection reset | `MailTMConnectionError` |
| HTTP 401 | `MailTMAuthError` |
| `read_inbox`, `read_message`, or `wait_for_message` before `login` | `MailTMNotAuthenticatedError` |
| HTTP 429 | `MailTMRateLimitError` |
| HTTP 5xx | `MailTMServerError`. A 503 with a numeric `Retry-After` above `max_delay` is `MailTMRateLimitError` when another attempt is still allowed |
| Any other non-2xx, including 404 and 422 | `MailTMAPIError` |
| 2xx body that is not valid JSON, is not a JSON object, lacks `hydra:member`, or lacks a required key | `MailTMResponseError` |
| Wait deadline elapsed | `MailTMWaitTimeoutError` |

`MailTMAPIError` carries `status_code` and `body` from the response. `body` is the parsed JSON, or the raw text when the error body is not JSON, or `""` when the body is empty. The message is `Mail.tm returned {status_code}`.

`MailTMTimeoutError`'s message names the operation and the timeout value, for example `GET /domains timed out (timeout=10.0)`. `MailTMConnectionError`'s message is `{METHOD} {path} could not connect`.

`MailTMNotAuthenticatedError` is raised before a request, with the message `Not authenticated. Call login() first.` Its `status_code` and `body` are `None`. It is a subclass of `MailTMAuthError`, so an `except MailTMAuthError` catches it.

`MailTMResponseError` names the missing key (`Response is missing {key}.`), a missing `hydra:member` (`Response is missing hydra:member.`), a `hydra:member` that is not a list (`Response hydra:member is not a list.`), or a body that is not valid JSON or not a JSON object. `status_code` is set when the body is not valid JSON or not a JSON object. It stays `None` when the failure is a missing key or a bad `hydra:member`. `body` is the payload, or the response text when the body is not valid JSON.

HTTP and transport failures are chained to the `requests` exception (`__cause__`). A response error is chained to the `KeyError`, `TypeError`, or JSON decode error that found the problem. `MailTMNotAuthenticatedError` and `MailTMWaitTimeoutError` are raised directly.

With `client`, `email`, and `password` from [Quick start](#quick-start), and `seen` from the wait example:

```python
from mailtm_client_wrapper import MailTMError, MailTMNotAuthenticatedError, MailTMWaitTimeoutError

try:
    message = client.wait_for_message(exclude_ids=seen)
except MailTMWaitTimeoutError as exc:
    print(exc.timeout)
except MailTMNotAuthenticatedError:
    client.login(email, password)
except MailTMError:
    raise
```

`except MailTMTimeoutError` does not catch `MailTMWaitTimeoutError`. Catch `MailTMError` when any library failure should be handled in one place.

## Message types

`MessageSummary` and `Message` are `TypedDict` annotations exported from `mailtm_client_wrapper`. `read_inbox` and `read_message` are annotated with them. The objects returned at runtime are the plain dicts the API sent. Keys are not renamed or dropped. Values are not parsed: `html` is whatever the server sent (the annotation types it as `list[str]`), and timestamp fields are left as sent. Unknown keys stay on the dict.

Validation checks that required keys are present. It does not check types or whether a value is null.

Required on every inbox summary and on a full message: `id`, `from`, `subject`, `createdAt`, `seen`, `hasAttachments`. A full message also requires `text` and `html`. A chosen domain requires `domain`. A token response requires `token`.

`intro` is optional on a summary. Other keys the annotations allow, and any key the server adds, are not required.

## Limitations

- A request timeout covers the connect phase and each socket read, which is the `requests` rule this client passes through. A body that keeps arriving can take longer than the timeout value. The client does not put a wall-clock deadline around a single request.
- `wait_for_message` checks its deadline only between polls. During an outage the current HTTP call can finish its own retries first. With the defaults that overshoot is about 33 seconds: three 10-second attempts, plus backoff of 1 second and 2 seconds, plus up to 25% jitter on those two sleeps. Pages inside one `read_inbox` poll, and the `read_message` that follows a match, are not cut short to the time remaining either.
- Whether Mail.tm sends `Retry-After` on 429 is unverified. When a numeric `Retry-After` is present on 429 or 503, the client follows the rules in [Retries](#retries).
- The real inbox page size is unverified. `read_inbox` does not assume a page size, and it does not require `hydra:view`. `get_domain` does not read past the first page of domains.
- Which message fields can be null is unverified. Required keys are presence checks only.
- The server-side token lifetime is unverified. The client never refreshes a token. A later 401 is `MailTMAuthError`; call `login()` again.
- Whether account creation is limited to one request per minute is unverified. `create_account` retries a 429 and does not treat any other status as a rate limit.

## Tests

From a checkout, after `uv sync`:

```bash
uv run pytest
```

That run does not contact Mail.tm. Tests that would otherwise send HTTP are mocked, and an unmocked request fails.

One smoke test calls the live `get_domain` and fails normally if that call fails. It is skipped unless `MAILTM_LIVE` is exactly `1`:

```bash
MAILTM_LIVE=1 uv run pytest -m live
```

The smoke test only looks up a domain. It does not create an account.

## Breaking changes

Compared with the previous client in this repository:

- Failures are `MailTMError` subclasses. They used to be a bare `Exception` with messages such as `Failed to fetch domain: ...`, `Error creating account: ...`, `Login failed: ...`, `Failed to fetch inbox: ...`, and `Failed to fetch message ...: ...`.
- Every request has a timeout. The constructor takes keyword-only `timeout` (default `10.0`) and `retry`. A request cannot be left unbounded.
- `read_inbox` returns every page in one list, de-duplicated by `id`. A missing `hydra:member` used to become `[]` and only the first page was requested. A failure on a later page now raises and does not return a partial list.
- `get_domain` returns the first active, non-private domain on the first page, and raises `MailTMResponseError` when none qualifies. It used to return the first member's `domain` whenever the list was non-empty.
- A 2xx body that is not a JSON object, or that omits a required key, raises `MailTMResponseError` instead of `KeyError` or a wrapped `Exception`.
- Transient failures are retried by default (3 attempts). `create_account` retries only 429.
- Python 3.12 or newer is required.

`wait_for_message`, `extract_between`, `RetryPolicy`, the exception types, and `Message` / `MessageSummary` are new. The full list is in [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE).
