class ErrorHandler:
    """
    «Control» ErrorHandler — UC-06 Handle API Failure (FR 1.2.1.1, NFR 2.1).

    Logs the failure (UC-06 step 2) and turns a OneMapError into a JSON error the
    browser shows as a dismissible banner, while the rest of the page keeps working.
    """

    USER_MESSAGE = "OneMap service currently unavailable"

    def log_error(self, endpoint: str, timestamp, code) -> None:
        """UC-06 step 2: write the endpoint, time and status code to Python logging."""
        raise NotImplementedError("Phase 7")

    def to_response(self, exc):
        """Return JsonResponse `{"error": "<user message>"}` with HTTP 502."""
        raise NotImplementedError("Phase 7")
