"""Common error types for uniconn."""


class TimeoutError(Exception):
    """Raised when a read or write operation times out."""

    def __init__(self, operation: str = "operation"):
        super().__init__(f"{operation} timed out")


class ConnectionClosedError(Exception):
    """Raised when an operation is attempted on a closed connection."""

    def __init__(self):
        super().__init__("connection is closed")


class ListenerClosedError(Exception):
    """Raised when the listener is closed."""

    def __init__(self):
        super().__init__("listener is closed")
