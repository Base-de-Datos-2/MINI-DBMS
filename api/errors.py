"""The one exception type the HTTP layer turns into an error envelope."""

from __future__ import annotations

from typing import Any

from .schemas import ERROR_STATUS


class ServiceError(Exception):
    """A failure with a stable code, safe to show to the user as-is."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        location: dict[str, Any] | None = None,
        statement: str | None = None,
        execution_plan: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
        session: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = ERROR_STATUS[code]
        self.message = message
        self.location = location
        self.statement = statement
        self.execution_plan = execution_plan
        self.details = details
        #: Session status after the failed call, when a session token was used.
        self.session = session
