"""Pull a literal span out of a string. This module makes no network calls."""


def extract_between(text: str, start: str, end: str) -> str | None:
    """Return the text between the first literal start marker and the next end marker.

    Markers are matched exactly and case-sensitively. The span is trimmed.
    A missing marker, or a span that is empty after trimming, returns None.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    _require_marker(start, "start")
    _require_marker(end, "end")

    start_index = text.find(start)
    if start_index < 0:
        return None
    after_start = start_index + len(start)
    end_index = text.find(end, after_start)
    if end_index < 0:
        return None
    extracted = text[after_start:end_index].strip()
    if extracted == "":
        return None
    return extracted


def _require_marker(marker: object, marker_name: str) -> None:
    if not isinstance(marker, str):
        raise TypeError(f"{marker_name} must be a string")
    if marker == "":
        raise ValueError(f"{marker_name} must not be empty")
