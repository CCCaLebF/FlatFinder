from django.db import models

from .flat import ResaleFlat


class FlatProximity(models.Model):
    """
    «Entity» FlatProximity (new, approved in PLAN §8) — pre-computed straight-line
    distances in metres from a flat to the nearest node of each category.

    Built by `compute_proximity` with a KD-tree (decision 9). Feeds the proximity
    sub-scores of the Fit Score (FR 2.2.2, UC-09) and the provisional walk-limit
    filter (FR 1.1.3). Null means the flat has no coordinates.
    """

    flat = models.OneToOneField(
        ResaleFlat, on_delete=models.CASCADE, primary_key=True, related_name="proximity")
    nearest_bus_stop_m = models.FloatField(null=True, blank=True)
    nearest_mrt_station_m = models.FloatField(null=True, blank=True)
    nearest_child_care_centre_m = models.FloatField(null=True, blank=True)
    nearest_hawker_centre_m = models.FloatField(null=True, blank=True)
    nearest_chas_clinic_m = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"Proximity for flat {self.flat_id}"
