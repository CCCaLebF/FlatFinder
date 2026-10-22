from django.db import models


class Amenity(models.Model):
    """
    «Entity» Amenity — abstract base for neighbourhood facilities (SRS data dictionary).

    Imported from data.gov.sg into our database, never fetched from OneMap (decision 5).
    Shown within 1 km of a selected flat (FR 2.3, UC-11) with a straight-line distance.
    """

    CHILD_CARE = "CHILD_CARE"
    HAWKER = "HAWKER"
    CHAS = "CHAS"
    TYPE_CHOICES = [
        (CHILD_CARE, "Child Care Centre"),
        (HAWKER, "Hawker Centre"),
        (CHAS, "CHAS Clinic"),
    ]
    TYPE_VALUE = None  # set by each concrete subclass

    name = models.CharField(max_length=256)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    postal_code = models.CharField(max_length=6, blank=True)
    address = models.CharField(max_length=512, blank=True)
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

    def save(self, *args, **kwargs):
        self.type = self.TYPE_VALUE
        super().save(*args, **kwargs)


class ChildCareCentre(Amenity):
    """«Entity» ChildCareCentre — the SRS's "pre-schools" category (FR 2.3.3)."""

    TYPE_VALUE = Amenity.CHILD_CARE

    class Meta(Amenity.Meta):
        pass


class HawkerCentre(Amenity):
    """«Entity» HawkerCentre (FR 2.3.4)."""

    TYPE_VALUE = Amenity.HAWKER

    class Meta(Amenity.Meta):
        pass


class ChasClinic(Amenity):
    """«Entity» ChasClinic — excludes polyclinics and hospitals (FR 2.3.5)."""

    TYPE_VALUE = Amenity.CHAS

    class Meta(Amenity.Meta):
        pass
