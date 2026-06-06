from __future__ import annotations


class UnifiProtectError(Exception):
    """Base class for all other UniFi Protect errors"""


class StreamError(UnifiProtectError):
    """Expcetion raised when trying to stream content"""


class DataDecodeError(UnifiProtectError):
    """Exception raised when trying to decode a UniFi Protect object"""


class WSDecodeError(UnifiProtectError):
    """Exception raised when decoding Websocket packet"""


class WSEncodeError(UnifiProtectError):
    """Exception raised when encoding Websocket packet"""


class ClientError(UnifiProtectError):
    """Base Class for all other UniFi Protect client errors"""


class BadRequest(ClientError):
    """Invalid request from API Client"""


class PublicOnlyModeError(BadRequest):
    """Private-API operation attempted on a public-only (API-key-only) client."""


class Invalid(ClientError):
    """Invalid return from Authorization Request."""


class NotAuthorized(PermissionError, BadRequest):
    """Wrong username, password or permission error."""


class GlobalAlarmManagerError(BadRequest):
    """Operation not available when global alarm manager is enabled."""


class ArmedModeError(BadRequest):
    """Operation not available while the arm alarm is armed."""


class NvrError(ClientError):
    """Other error."""
