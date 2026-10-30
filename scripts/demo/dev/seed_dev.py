"""Dev-only seed for FlatFinder: synthetic transactions on the repo's real block coordinates.
Used only to develop the recording script in the cloud workspace (data.gov.sg is unreachable here).
Run from the repo root: python manage.py shell < scripts/demo/dev/seed_dev.py, then python manage.py compute_proximity
"""
import csv, random, math
from datetime import date
from decimal import Decimal
from backend.core.models import (ResaleFlat, Town, BusStop, MrtStation,
                                 ChildCareCentre, HawkerCentre, ChasClinic)

random.seed(7)
TOWNS = {
    "ANG MO KIO": (1.3691, 103.8454), "BEDOK": (1.3236, 103.9273), "BISHAN": (1.3526, 103.8352),
    "BUKIT BATOK": (1.3590, 103.7637), "BUKIT MERAH": (1.2819, 103.8239), "BUKIT PANJANG": (1.3774, 103.7719),
    "BUKIT TIMAH": (1.3294, 103.8021), "CENTRAL AREA": (1.2894, 103.8500), "CHOA CHU KANG": (1.3840, 103.7470),
    "CLEMENTI": (1.3162, 103.7649), "GEYLANG": (1.3201, 103.8918), "HOUGANG": (1.3612, 103.8863),
    "JURONG EAST": (1.3329, 103.7436), "JURONG WEST": (1.3404, 103.7090), "KALLANG/WHAMPOA": (1.3100, 103.8651),
    "MARINE PARADE": (1.3020, 103.8971), "PASIR RIS": (1.3721, 103.9474), "PUNGGOL": (1.3984, 103.9072),
    "QUEENSTOWN": (1.2942, 103.7861), "SEMBAWANG": (1.4491, 103.8185), "SENGKANG": (1.3868, 103.8914),
    "SERANGOON": (1.3554, 103.8679), "TAMPINES": (1.3496, 103.9568), "TOA PAYOH": (1.3343, 103.8563),
    "WOODLANDS": (1.4382, 103.7890), "YISHUN": (1.4304, 103.8354),
}
TYPES = [("2 ROOM", 45, 330_000), ("3 ROOM", 68, 420_000), ("4 ROOM", 93, 560_000),
         ("5 ROOM", 113, 680_000), ("EXECUTIVE", 140, 820_000)]
STOREYS = ["01 TO 03", "04 TO 06", "07 TO 09", "10 TO 12", "13 TO 15", "16 TO 18", "19 TO 21", "22 TO 24"]
MODELS = ["Improved", "New Generation", "Model A", "Premium Apartment", "Simplified"]

def nearest_town(lat, lng):
    return min(TOWNS, key=lambda t: (TOWNS[t][0]-lat)**2 + (TOWNS[t][1]-lng)**2)

for M in (ResaleFlat, Town, BusStop, MrtStation, ChildCareCentre, HawkerCentre, ChasClinic):
    M.objects.all().delete()
Town.objects.bulk_create([Town(name=n, centroid_lat=a, centroid_lng=b) for n, (a, b) in TOWNS.items()])

rows = list(csv.DictReader(open("database/data/flat_coordinates.csv")))
flats = []
for r in rows:
    lat, lng = float(r["latitude"]), float(r["longitude"])
    town = nearest_town(lat, lng)
    lcd = random.randint(1972, 2020)
    central = 1 + max(0, 0.12 - math.hypot(lat-1.29, lng-103.85)) * 3
    for _ in range(random.randint(1, 4)):
        ft, area, base = random.choice(TYPES)
        age_factor = 0.65 + 0.35 * (lcd - 1970) / 50
        price = int(base * central * age_factor * random.uniform(0.85, 1.2) / 1000) * 1000
        rem = 99 - (2026.8 - lcd)
        flats.append(ResaleFlat(
            month=date(2026, random.randint(1, 9), 1), town=town, flat_type=ft, block=r["block"],
            street_name=r["street_name"], storey_range=random.choice(STOREYS),
            floor_area_sqm=area + random.choice([-3, 0, 2, 5]), flat_model=random.choice(MODELS),
            lease_commence_date=lcd, remaining_lease=round(rem, 2),
            remaining_lease_raw=f"{int(rem)} years {int((rem % 1) * 12):02d} months",
            resale_price=Decimal(price), latitude=lat, longitude=lng))
ResaleFlat.objects.bulk_create(flats, batch_size=2000)

def scatter(n, spread):
    pts = random.sample(rows, n)
    return [(float(p["latitude"]) + random.uniform(-spread, spread),
             float(p["longitude"]) + random.uniform(-spread, spread)) for p in pts]

BusStop.objects.bulk_create([BusStop(name=f"Bus Stop {10000+i}", stop_code=str(10000+i), type="BUS",
                             latitude=a, longitude=b) for i, (a, b) in enumerate(scatter(4000, 0.002))])
MrtStation.objects.bulk_create([MrtStation(name=f"{t.title()} MRT Station", exit_code=f"Exit {chr(65+k)}", type="MRT",
                                latitude=TOWNS[t][0]+random.uniform(-.004,.004), longitude=TOWNS[t][1]+random.uniform(-.004,.004))
                                for t in TOWNS for k in range(3)])
ChildCareCentre.objects.bulk_create([ChildCareCentre(name=f"Little Sprouts Child Care {i}", type="CHILD_CARE",
                                     latitude=a, longitude=b) for i, (a, b) in enumerate(scatter(1200, 0.003))])
HawkerCentre.objects.bulk_create([HawkerCentre(name=f"{t.title()} Hawker Centre {k+1}", type="HAWKER",
                                  latitude=TOWNS[t][0]+random.uniform(-.01,.01), longitude=TOWNS[t][1]+random.uniform(-.01,.01))
                                  for t in TOWNS for k in range(4)])
ChasClinic.objects.bulk_create([ChasClinic(name=f"Family Clinic {i}", type="CHAS",
                                latitude=a, longitude=b) for i, (a, b) in enumerate(scatter(900, 0.003))])
print("flats", ResaleFlat.objects.count())
