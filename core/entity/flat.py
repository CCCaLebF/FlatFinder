from django.db import models


class ResaleFlat(models.Model):
    """
    «Entity» ResaleFlat — one HDB resale transaction from the last 12 months (decision 7).

    Holds the fields shown for every flat (FR 2.2.3.1.1–2.2.3.1.8). The Fit Score
    (FR 2.2.3.1.9) is not stored; it is calculated per SearchQuery (UC-09).

    Coordinates are nullable: the resale dataset has none, and they arrive later via
    `import_flat_coordinates` or the dev-only `assign_approximate_coords` (PLAN §3.3).
    Flats without coordinates still appear in list results but not as map pins.
    """

    month = models.DateField(help_text="Transaction month (first day of the month).")
    town = models.CharField(max_length=64)
    flat_type = models.CharField(max_length=32)                       # FR 2.2.3.1.3
    block = models.CharField(max_length=16)                           # FR 2.2.3.1.2
    street_name = models.CharField(max_length=128)                    # FR 2.2.3.1.1
    storey_range = models.CharField(max_length=16)                    # FR 2.2.3.1.5
    floor_area_sqm = models.FloatField()                              # FR 2.2.3.1.4
    flat_model = models.CharField(max_length=64)
    lease_commence_date = models.PositiveSmallIntegerField()          # FR 2.2.3.1.7 (year)
    remaining_lease = models.FloatField(
        help_text="Decimal years as of the import date: 99 - years since lease_commence_date.")
    remaining_lease_raw = models.CharField(
        max_length=64, blank=True, help_text="The dataset's original string, e.g. '61 years 04 months'.")
    resale_price = models.DecimalField(max_digits=12, decimal_places=2)  # FR 2.2.3.1.6

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    coords_approximate = models.BooleanField(
        default=False, help_text="True when the coordinates are the town centroid (dev fallback).")

    class Meta:
        indexes = [
            models.Index(fields=["town"]),
            models.Index(fields=["flat_type"]),
            models.Index(fields=["resale_price"]),
            models.Index(fields=["remaining_lease"]),
            models.Index(fields=["latitude"]),
            models.Index(fields=["longitude"]),
        ]

    def __str__(self):
        return f"Blk {self.block} {self.street_name} ({self.flat_type}, {self.month:%Y-%m})"

    @property
    def has_coords(self):
        return self.latitude is not None and self.longitude is not None
