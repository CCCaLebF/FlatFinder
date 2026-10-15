"""
Downloads the PLAN §3.1 datasets from data.gov.sg into data/raw/.

Uses the public API: GET /v1/public/api/datasets/{id}/poll-download returns a temporary
file URL. If a dataset isn't ready, POST .../initiate-download first. Without an API key
the API is rate limited (response code 24), so requests back off and retry.
"""
import time

import requests
from django.core.management.base import BaseCommand, CommandError

from core.management.datasets import DATASETS, raw_path

API = "https://api-open.data.gov.sg/v1/public/api/datasets/{id}/{action}"
RATE_LIMITED = 24


class Command(BaseCommand):
    help = "Download the raw datasets from data.gov.sg into data/raw/ (skips files already there)."

    def add_arguments(self, parser):
        parser.add_argument("keys", nargs="*", help=f"Datasets to fetch (default: all): {', '.join(DATASETS)}")
        parser.add_argument("--force", action="store_true", help="Re-download files that already exist.")

    def handle(self, *args, keys, force, **options):
        unknown = set(keys) - set(DATASETS)
        if unknown:
            raise CommandError(f"Unknown dataset(s): {', '.join(sorted(unknown))}")
        for key in keys or DATASETS:
            path = raw_path(key)
            if path.exists() and not force:
                self.stdout.write(f"{key}: already at {path}, skipping")
                continue
            dataset_id = DATASETS[key][0]
            url = self._file_url(dataset_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            with requests.get(url, stream=True, timeout=120) as response:
                response.raise_for_status()
                with open(path, "wb") as fh:
                    for chunk in response.iter_content(chunk_size=1 << 16):
                        fh.write(chunk)
            self.stdout.write(self.style.SUCCESS(f"{key}: saved {path} ({path.stat().st_size:,} bytes)"))

    def _call(self, dataset_id, action, method="get"):
        for _ in range(10):
            response = requests.request(method, API.format(id=dataset_id, action=action), timeout=30)
            body = response.json()
            if body.get("code") != RATE_LIMITED:
                return body
            time.sleep(12)
        raise CommandError(f"{dataset_id}: still rate limited after 10 attempts.")

    def _file_url(self, dataset_id):
        body = self._call(dataset_id, "poll-download")
        if not (body.get("data") or {}).get("url"):
            self._call(dataset_id, "initiate-download", method="post")
            for _ in range(10):
                time.sleep(3)
                body = self._call(dataset_id, "poll-download")
                if (body.get("data") or {}).get("url"):
                    break
        url = (body.get("data") or {}).get("url")
        if not url:
            raise CommandError(f"{dataset_id}: no download URL ({body.get('errorMsg') or body}).")
        return url
