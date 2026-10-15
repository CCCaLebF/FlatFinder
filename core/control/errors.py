import logging

from django.http import JsonResponse
from django.utils import timezone

logger = logging.getLogger("core.onemap")


class ErrorHandler:
    """
    «Control» ErrorHandler — UC-06 Handle API Failure (FR 1.2.1.1, NFR 2.1).

    Logs the failure (UC-06 step 2) and turns a OneMapError into a JSON error the
    browser shows as a dismissible banner, while the rest of the page keeps working.
    """

    USER_MESSAGE = "OneMap service currently unavailable. Please try again later."

    def log_error(self, endpoint: str, timestamp, code) -> None:
        """UC-06 step 2: write the endpoint, time and status code to Python logging."""
        logger.warning("OneMap failure endpoint=%s time=%s code=%s", endpoint, timestamp.isoformat(), code)

    def handle(self, exc) -> str:
        """Log a OneMapError and return the message to show the user."""
        self.log_error(getattr(exc, "endpoint", "unknown"), timezone.now(), getattr(exc, "code", None))
        return self.USER_MESSAGE

    def to_response(self, exc):
        """Return JsonResponse `{"error": "<user message>"}` with HTTP 502."""
        return JsonResponse({"error": self.handle(exc)}, status=502)
