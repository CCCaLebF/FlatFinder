"""«Boundary» UI: one view module per UI class in the class diagram."""
from django.http import HttpResponse


def not_implemented(phase: int) -> HttpResponse:
    """Placeholder response for a route whose build phase (PLAN §7) hasn't happened yet."""
    return HttpResponse(f"Not built yet (PLAN §7 phase {phase}).", status=501, content_type="text/plain")
