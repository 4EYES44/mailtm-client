"""Typed failures raised by the Mail.tm client."""


class MailTMError(Exception):
    """Root for every failure the library raises."""


class MailTMTimeoutError(MailTMError):
    """A single request timed out."""


class MailTMConnectionError(MailTMError):
    """The request never produced an HTTP response."""


class _ResponseDetails:
    """HTTP status and body shared by API errors and response errors."""

    status_code: int | None
    body: object

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: object = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class MailTMAPIError(_ResponseDetails, MailTMError):
    """The server answered with a non-2xx status."""


class MailTMAuthError(MailTMAPIError):
    """The server rejected the credentials or token."""


class MailTMNotAuthenticatedError(MailTMAuthError):
    """An authenticated call was made before login()."""


class MailTMRateLimitError(MailTMAPIError):
    """The server refused the call with 429."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: object = None,
        retry_after: int | float | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, body=body)
        self.retry_after = retry_after


class MailTMServerError(MailTMAPIError):
    """The server answered with a 5xx status."""


class MailTMResponseError(_ResponseDetails, MailTMError):
    """A 2xx body was not usable JSON."""


class MailTMWaitTimeoutError(MailTMError):
    """The wait helper reached its deadline without a matching message."""

    def __init__(self, message: str, *, timeout: float) -> None:
        super().__init__(message)
        self.timeout = timeout
