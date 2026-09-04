"""Domain-level errors. Stdlib only."""


class CalendarError(Exception):
    """Base class for all calendar-specific errors."""


class UnknownEventError(CalendarError):
    """Raised when an operation names an event id that has no stored row."""


class UnknownPostError(CalendarError):
    """Raised when an operation names a post id the crossposting context doesn't know."""


class PublishError(CalendarError):
    """Raised when composing or publishing a post fails.

    This is the calendar's own error, wrapping whatever crossposting's
    PostPublisher adapter raised (see calendar/infrastructure/crossposting.py):
    the calendar's application layer and templates only ever need to know
    about diffus.calendar.domain.errors, never diffus.crossposting.domain.errors.
    """
