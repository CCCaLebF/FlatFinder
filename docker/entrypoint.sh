#!/bin/sh
# Wait for the database, apply migrations, then run the container command.
# Does NOT import data: that is slow and stays a deliberate step (manage.py load_all).
set -e

echo "Waiting for the database..."
python - <<'PY'
import time

import django
from django.db import connections
from django.db.utils import OperationalError

django.setup()
for attempt in range(60):
    try:
        connections["default"].ensure_connection()
        break
    except OperationalError:
        time.sleep(1)
else:
    raise SystemExit("Database did not become available within 60 s.")
PY

python manage.py migrate --noinput

exec "$@"
