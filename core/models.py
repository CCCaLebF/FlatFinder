"""Re-exports the Django models in core/entity/ so Django can find them (PLAN §5)."""
from core.entity.amenity import ChasClinic, ChildCareCentre, HawkerCentre  # noqa: F401
from core.entity.flat import ResaleFlat  # noqa: F401
from core.entity.proximity import FlatProximity  # noqa: F401
from core.entity.town import Town  # noqa: F401
from core.entity.transport import BusStop, MrtStation  # noqa: F401
