import pytest

from mailtm_client_wrapper import extract_between

SPEC_BODY = "hello , this is the otp for the email : 1234 , dont share it with anyone"


@pytest.mark.parametrize(
    ("text", "start", "end", "expected"),
    [
        pytest.param(SPEC_BODY, "the email : ", " , dont", "1234", id="spec example"),
        pytest.param(
            "hello , this is the otp , dont share it",
            "the email : ",
            " , dont",
            None,
            id="missing start",
        ),
        pytest.param(
            "hello , this is the otp for the email : 1234",
            "the email : ",
            " , dont",
            None,
            id="missing end",
        ),
        pytest.param(
            " , dont share it, then the email : 1234",
            "the email : ",
            " , dont",
            None,
            id="end only before start",
        ),
        pytest.param(
            "the email :  , dont share it",
            "the email : ",
            " , dont",
            None,
            id="empty value",
        ),
        pytest.param(
            "the email : \n\t  , dont share it",
            "the email : ",
            " , dont",
            None,
            id="whitespace-only value",
        ),
        pytest.param(
            "the email : \n 1234 \t , dont share it",
            "the email : ",
            " , dont",
            "1234",
            id="whitespace around the value",
        ),
        pytest.param(
            "the email : 12  34 , dont and the email : 9999 , dont",
            "the email : ",
            " , dont",
            "12  34",
            id="repeated markers",
        ),
        pytest.param(SPEC_BODY, "The Email : ", " , dont", None, id="start case differs"),
        pytest.param(SPEC_BODY, "the email : ", " , DONT", None, id="end case differs"),
    ],
)
def test_extract_between_returns_the_span_between_literal_markers(
    text, start, end, expected
):
    """Markers are exact, and the span between the first pair is returned trimmed."""
    assert extract_between(text, start, end) == expected


@pytest.mark.parametrize(
    ("text", "start", "end", "error"),
    [
        pytest.param("body", "", "end", ValueError, id="empty start"),
        pytest.param("body", "start", "", ValueError, id="empty end"),
        pytest.param("body", None, "end", TypeError, id="non-string start"),
        pytest.param("body", "start", None, TypeError, id="non-string end"),
        pytest.param("body", 1, "end", TypeError, id="numeric start"),
        pytest.param("body", "start", 1, TypeError, id="numeric end"),
        pytest.param(None, "start", "end", TypeError, id="non-string text"),
        pytest.param(1234, "start", "end", TypeError, id="numeric text"),
    ],
)
def test_extract_between_rejects_empty_or_non_string_arguments(text, start, end, error):
    """Empty markers and non-string arguments are rejected before any search."""
    with pytest.raises(error):
        extract_between(text, start, end)
