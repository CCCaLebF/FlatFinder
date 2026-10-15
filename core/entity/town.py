from django.db import models


class Town(models.Model):
    """
    «Entity» Town (new, approved in PLAN §8) — a resale-dataset town and its centroid.

    Used for the area-count markers when the map is zoomed out (FR 2.1.1, decision 8)
    and for the dev-only approximate-coordinates fallback (PLAN §3.3).
    """

    name = models.CharField(max_length=64, unique=True, help_text="Matches ResaleFlat.town.")
    centroid_lat = models.FloatField()
    centroid_lng = models.FloatField()

    def __str__(self):
        return self.name
