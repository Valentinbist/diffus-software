"""Domain-level errors. Stdlib only."""


class CalendarError(Exception):
    """Base class for all calendar-specific errors."""


class UnknownEventError(CalendarError):
    """Raised when an operation names an event id that has no stored row."""


class UnknownPostError(CalendarError):
    """Raised when an operation names a post id the crossposting context doesn't know."""
