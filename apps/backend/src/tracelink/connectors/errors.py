from __future__ import annotations


class ConnectorError(RuntimeError):
    code = "CONNECTOR_ERROR"
    public_message = "research connector failed"

    def __init__(self, message: str | None = None, *, status_code: int | None = None) -> None:
        super().__init__(message or self.public_message)
        self.status_code = status_code


class ConnectorTimeoutError(ConnectorError):
    code = "CONNECTOR_TIMEOUT"
    public_message = "the public source timed out"


class ConnectorRateLimitError(ConnectorError):
    code = "CONNECTOR_RATE_LIMITED"
    public_message = "the public source rate limit was reached"


class ConnectorFetchError(ConnectorError):
    code = "CONNECTOR_FETCH_FAILED"
    public_message = "the public source could not be fetched"


class UnsafeUrlError(ConnectorError):
    code = "UNSAFE_URL"
    public_message = "the URL is not safe to fetch"


class UnsupportedContentTypeError(ConnectorError):
    code = "UNSUPPORTED_CONTENT_TYPE"
    public_message = "the public source returned an unsupported content type"


class ResponseTooLargeError(ConnectorError):
    code = "RESPONSE_TOO_LARGE"
    public_message = "the public source response is too large"


class InvalidConnectorInputError(ConnectorError):
    code = "INVALID_CONNECTOR_INPUT"
    public_message = "the connector input is invalid"
