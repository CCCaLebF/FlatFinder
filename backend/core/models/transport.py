from django.db import models


class TransportNode(models.Model):
    """
    «Entity» TransportNode — abstract base for public-transit points (SRS data dictionary).

    Walking distance from a flat to a node is calculated on demand via the OneMap
    Routing API (UC-04); the straight-line distance used for ranking is pre-computed
    in FlatProximity. Evaluated against the user's walking limits (FR 1.1.3).
    """

    BUS = "BUS"
    MRT = "MRT"
    TYPE_CHOICES = [(BUS, "Bus Stop"), (MRT, "MRT Station")]

    name = models.CharField(max_length=128)
    type = models.CharField(max_length=3, choices=TYPE_CHOICES)
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=["latitude"], name="%(class)s_lat_idx"),
            models.Index(fields=["longitude"], name="%(class)s_lng_idx"),
        ]

    def __str__(self):
        return self.name


class BusStop(TransportNode):
    """«Entity» BusStop — an LTA bus stop (FR 1.1.3.1, FR 2.3.1)."""

    stop_code = models.CharField(max_length=8, unique=True)

    class Meta(TransportNode.Meta):
        pass

    def save(self, *args, **kwargs):
        self.type = TransportNode.BUS
        super().save(*args, **kwargs)


class MrtStation(TransportNode):
    """
    «Entity» MrtStation — one row per station **exit** (PLAN §3.1), so distances use
    the nearest exit. Nearby-station lists show each station name once (FR 1.1.3.2, FR 2.3.2).
    Not unique on (name, exit_code): the LTA file has a few exits that share a label
    but sit at different points, and each is kept.
    """

    exit_code = models.CharField(max_length=32, blank=True)

    class Meta(TransportNode.Meta):
        pass

    def save(self, *args, **kwargs):
        self.type = TransportNode.MRT
        super().save(*args, **kwargs)
