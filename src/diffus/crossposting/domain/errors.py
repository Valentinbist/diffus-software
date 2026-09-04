"""Domain-level errors. Stdlib only."""


class ConnectorError(Exception):
    """Base class for all connector-specific errors."""


class NotConnectedError(ConnectorError):
    """Raised when an operation requires a stored Instagram token but none exists."""


class DeliveryError(ConnectorError):
    """Raised when delivering a post to a sink (e.g. Telegram) fails."""


class DraftError(ConnectorError):
    """Raised for anything wrong with a draft: German message, shown to the user as-is."""


class InvalidImageError(DraftError):
    """Raised when an uploaded image can't be normalised (unreadable, too large)."""


class UploadTooLargeError(DraftError):
    """Raised when an upload exceeds the image-count or total-size limit."""


class PublishError(ConnectorError):
    """Raised when Instagram publishing fails: container creation, readiness, or media_publish."""
