"""Domain-level errors. Stdlib only."""


class ConnectorError(Exception):
    """Base class for all connector-specific errors."""


class NotConnectedError(ConnectorError):
    """Raised when an operation requires a stored Instagram token but none exists."""


class DeliveryError(ConnectorError):
    """Raised when delivering a post to a sink (e.g. Telegram) fails."""
