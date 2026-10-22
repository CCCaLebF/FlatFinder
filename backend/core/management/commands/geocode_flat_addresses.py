"""
One-off, offline tool (docs/GEOCODING_PLAN.md, decision 6): looks up every distinct resale-flat
(block, street_name) on the OneMap search API and writes the CSV that `import_flat_coordinates`
loads. It never writes to the database, and the running app never calls it.

Requests go one at a time, paced to `--rate` per second. Every row is flushed as soon as it is
written, so a stopped run loses nothing: run the same command again and it resumes.
"""
import csv
import difflib
import os
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backend.core.integrations.onemap import OneMapError, OneMapSearchGateway
from backend.core.services.distance import StraightLineDistance
from backend.core.models import ResaleFlat, Town
from backend.core.management.commands.import_flat_coordinates import SG_BOUNDS
from backend.core.management.parsers import normalise_address_part

OUT_COLUMNS = ["block", "street_name", "latitude", "longitude",
               "postal", "onemap_road_name", "match_method", "query"]
UNMATCHED_COLUMNS = ["block", "street_name", "reason", "candidates"]

# HDB street-name abbreviations, whole words only (GEOCODING_PLAN §3.3). Checked against every
# word in the dataset's street names on 15 Oct 2026. `ST.` (with the dot) only appears as the
# saint in ST. GEORGE'S RD / LANE; plain `ST` is always STREET.
ABBREVIATIONS = {
    "AVE": "AVENUE", "ST": "STREET", "RD": "ROAD", "DR": "DRIVE", "CRES": "CRESCENT", "CL": "CLOSE",
    "PL": "PLACE", "CTRL": "CENTRAL", "NTH": "NORTH", "STH": "SOUTH", "UPP": "UPPER", "LOR": "LORONG",
    "JLN": "JALAN", "BT": "BUKIT", "KG": "KAMPONG", "TG": "TANJONG", "C'WEALTH": "COMMONWEALTH",
    "TER": "TERRACE", "HTS": "HEIGHTS", "PK": "PARK", "GDNS": "GARDENS", "SQ": "SQUARE",
    "CTR": "CENTRE", "MKT": "MARKET", "ST.": "SAINT",
}
FUZZY_MIN_RATIO = 0.85
FAR_FROM_TOWN_M = 6000
BACKOFF_S = (10, 30, 60, 120, 120)  # waits before retries 1-5; the run stops if retry 5 fails
MIN_RATE = 0.25
PROGRESS_EVERY = 100
# When both queries fail, report the most specific reason.
REASON_RANK = {"no_results": 0, "block_mismatch": 1, "road_mismatch": 2, "ambiguous": 3, "out_of_bounds": 4}


class StopRun(Exception):
    """The run cannot continue (e.g. OneMap keeps refusing); it can be resumed later."""


def expand_street(street: str) -> str:
    """The street name with HDB abbreviations written out, e.g. C'WEALTH AVE -> COMMONWEALTH AVENUE."""
    return " ".join(ABBREVIATIONS.get(word, word) for word in normalise_address_part(street).split())


def pick_result(results: list, block: str, expanded_street: str):
    """
    Choose the result for this block and street. Returns `(result, "exact" | "fuzzy")`, or
    `(None, reason)` with reason one of no_results, block_mismatch, road_mismatch, ambiguous.
    """
    if not results:
        return None, "no_results"
    same_block = [r for r in results if normalise_address_part(r.get("BLK_NO") or "") == block]
    if not same_block:
        return None, "block_mismatch"
    for result in same_block:
        if normalise_address_part(result.get("ROAD_NAME") or "") == expanded_street:
            return result, "exact"
    close = {}  # road name -> first result; several results can share one address
    for result in same_block:
        road = normalise_address_part(result.get("ROAD_NAME") or "")
        if difflib.SequenceMatcher(None, road, expanded_street).ratio() >= FUZZY_MIN_RATIO:
            close.setdefault(road, result)
    if len(close) == 1:
        return next(iter(close.values())), "fuzzy"
    return None, "ambiguous" if close else "road_mismatch"


def result_coords(result: dict):
    """`(lat, lng)` of a result, or None if it is missing or outside Singapore."""
    try:
        lat, lng = float(result["LATITUDE"]), float(result["LONGITUDE"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (SG_BOUNDS["lat"][0] <= lat <= SG_BOUNDS["lat"][1]
            and SG_BOUNDS["lng"][0] <= lng <= SG_BOUNDS["lng"][1]):
        return None
    return lat, lng


def format_candidates(results: list) -> str:
    return " | ".join(f"{r.get('BLK_NO', '')} {r.get('ROAD_NAME', '')} ({r.get('POSTAL', '')})"
                      for r in results[:3])


def is_transient(exc: OneMapError) -> bool:
    """Worth waiting and retrying: rate limit, timeout, network error or a 5xx."""
    return exc.code in (429, "timeout", "network") or (isinstance(exc.code, int) and exc.code >= 500)


def read_rows(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def row_key(row: dict) -> tuple:
    return normalise_address_part(row.get("block") or ""), normalise_address_part(row.get("street_name") or "")


class Pacer:
    """Keeps requests at most `rate` per second, one at a time."""

    def __init__(self, rate: float):
        self.rate = rate
        self._last = None

    def wait(self):
        if self._last is not None:
            delay = 1 / self.rate - (time.monotonic() - self._last)
            if delay > 0:
                time.sleep(delay)
        self._last = time.monotonic()


class Command(BaseCommand):
    help = ("Offline, one-off: geocode every distinct flat (block, street_name) with OneMap search and "
            "write a CSV for import_flat_coordinates. Never touches the database. Re-run to resume.")

    def add_arguments(self, parser):
        parser.add_argument("--out", default=str(settings.DATA_DIR / "flat_coordinates.csv"),
                            help="Output CSV; unmatched pairs go to <name>_unmatched.csv beside it.")
        parser.add_argument("--rate", type=float, default=1.0, help="Max requests per second (default 1.0).")
        parser.add_argument("--limit", type=int, default=None, help="Look up at most N pairs this run.")
        parser.add_argument("--retry-unmatched", action="store_true",
                            help="Try the pairs in the unmatched file again.")

    def handle(self, *args, out, rate, limit, retry_unmatched, **options):
        if rate <= 0:
            raise CommandError("--rate must be positive.")
        out_path = Path(out)
        unmatched_path = out_path.with_name(f"{out_path.stem}_unmatched{out_path.suffix or '.csv'}")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        self.gateway = OneMapSearchGateway()
        self.pacer = Pacer(rate)
        self.rate_halved = False
        self.rate_limited = 0
        self.requests = 0
        self.strategy = StraightLineDistance()
        self.centroids = {t.name: (t.centroid_lat, t.centroid_lng) for t in Town.objects.all()}

        towns = {}
        for block, street, town in ResaleFlat.objects.values_list("block", "street_name", "town").distinct():
            towns.setdefault((block, street), town)

        matched_keys = {row_key(r) for r in read_rows(out_path)}
        unmatched = {row_key(r): r for r in read_rows(unmatched_path)}
        if retry_unmatched:
            pending = sorted(k for k in unmatched if k not in matched_keys)
        else:
            pending = sorted(k for k in towns if k not in matched_keys and k not in unmatched)
        skipped = len(towns) - len(pending) if not retry_unmatched else 0
        if limit is not None:
            pending = pending[:limit]
        self.stdout.write(
            f"{len(towns):,} distinct addresses; {len(matched_keys):,} already matched, "
            f"{len(unmatched):,} already unmatched. Looking up {len(pending):,} "
            f"{'unmatched pairs again' if retry_unmatched else 'pairs'} at up to {rate:g} requests/s.")

        methods, reasons, far = Counter(), Counter(), 0
        started = time.monotonic()
        out_fh, out_writer = self._open_for_append(out_path, OUT_COLUMNS)
        un_fh = un_writer = None
        if not retry_unmatched:
            un_fh, un_writer = self._open_for_append(unmatched_path, UNMATCHED_COLUMNS)
        stopped = None
        done = 0
        try:
            for block, street in pending:
                row, ok = self.lookup(block, street, towns.get((block, street)))
                if ok:
                    out_writer.writerow(row)
                    out_fh.flush()
                    methods[row["match_method"].split("+")[0]] += 1
                    far += "far_from_town" in row["match_method"]
                    if retry_unmatched:
                        unmatched.pop((block, street), None)
                        self._rewrite(unmatched_path, UNMATCHED_COLUMNS, unmatched.values())
                else:
                    reasons[row["reason"]] += 1
                    if retry_unmatched:
                        unmatched[(block, street)] = row
                        self._rewrite(unmatched_path, UNMATCHED_COLUMNS, unmatched.values())
                    else:
                        un_writer.writerow(row)
                        un_fh.flush()
                done += 1
                if done % PROGRESS_EVERY == 0:
                    self._progress(done, len(pending), sum(methods.values()), started)
        except StopRun as exc:
            stopped = str(exc)
        except KeyboardInterrupt:
            stopped = "Interrupted."
        finally:
            out_fh.close()
            if un_fh:
                un_fh.close()

        self._summary(done, methods, reasons, far, started, out_path, unmatched_path)
        if stopped:
            self.stderr.write(self.style.WARNING(f"{stopped} Run the same command again to resume."))
        elif skipped:
            self.stdout.write(f"({skipped:,} pairs were skipped: already in the output files.)")

    # --- Lookup -----------------------------------------------------------------------

    def lookup(self, block: str, street: str, town: str):
        """Returns `(row, True)` for a match or `(unmatched_row, False)`."""
        expanded = expand_street(street)
        queries = [(f"{block} {street}", "")]
        if expanded != street:
            queries.append((f"{block} {expanded}", "expanded"))
        reason, candidates = None, ""
        for query, prefix in queries:
            results = self.search(query)
            result, outcome = pick_result(results, block, expanded)
            if result is not None:
                coords = result_coords(result)
                if coords is not None:
                    method = (prefix or "exact") if outcome == "exact" else "_".join(filter(None, [prefix, "fuzzy"]))
                    if self._far_from_town(coords, town):
                        method += "+far_from_town"
                    return {
                        "block": block, "street_name": street, "latitude": coords[0], "longitude": coords[1],
                        "postal": result.get("POSTAL", ""), "onemap_road_name": result.get("ROAD_NAME", ""),
                        "match_method": method, "query": query,
                    }, True
                outcome = "out_of_bounds"
            if reason is None or REASON_RANK[outcome] >= REASON_RANK[reason]:
                reason = outcome
                candidates = format_candidates(results) or candidates
        return {"block": block, "street_name": street, "reason": reason, "candidates": candidates}, False

    def search(self, query: str) -> list:
        """One paced search, retried with backoff on a 429, timeout or network failure."""
        for attempt in range(len(BACKOFF_S) + 1):
            self.pacer.wait()
            self.requests += 1
            try:
                return self.gateway.search_addresses(query)
            except OneMapError as exc:
                if not is_transient(exc):
                    raise StopRun(f"OneMap search failed ({exc.code}) for {query!r}.")
                if exc.code == 429:
                    self.rate_limited += 1
                    if not self.rate_halved:
                        self.rate_halved = True
                        self.pacer.rate = max(MIN_RATE, self.pacer.rate / 2)
                        self.stdout.write(f"Rate-limited (429): slowing to {self.pacer.rate:g} requests/s.")
                if attempt == len(BACKOFF_S):
                    break
                wait = BACKOFF_S[attempt]
                self.stdout.write(f"OneMap {exc.code} for {query!r}; retry {attempt + 1} in {wait} s.")
                time.sleep(wait)
        raise StopRun(f"{len(BACKOFF_S)} retries in a row failed for {query!r}.")

    def _far_from_town(self, coords, town) -> bool:
        centroid = self.centroids.get(town)
        return centroid is not None and self.strategy.distance_m(coords, centroid) > FAR_FROM_TOWN_M

    # --- Files and reporting ----------------------------------------------------------

    @staticmethod
    def _open_for_append(path: Path, columns: list):
        fresh = not path.exists() or path.stat().st_size == 0
        if not fresh:
            with open(path, "rb") as fh:  # a hand-edited file may lack a final newline
                fh.seek(-1, os.SEEK_END)
                needs_newline = fh.read(1) not in (b"\n", b"\r")
        fh = open(path, "a", encoding="utf-8", newline="")
        if not fresh and needs_newline:
            fh.write("\n")
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        if fresh:
            writer.writeheader()
            fh.flush()
        return fh, writer

    @staticmethod
    def _rewrite(path: Path, columns: list, rows):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)

    def _progress(self, done, total, matched, started):
        elapsed = time.monotonic() - started
        per_pair = elapsed / done
        finish = datetime.now() + timedelta(seconds=per_pair * (total - done))
        self.stdout.write(
            f"{done:,}/{total:,} done, {matched / done:.1%} matched, rate {self.pacer.rate:g} requests/s, "
            f"ETA {finish:%H:%M}.")

    def _summary(self, done, methods, reasons, far, started, out_path, unmatched_path):
        elapsed = timedelta(seconds=round(time.monotonic() - started))
        matched = sum(methods.values())
        fmt = lambda c: ", ".join(f"{k} {v:,}" for k, v in c.most_common()) or "none"  # noqa: E731
        self.stdout.write(self.style.SUCCESS(
            f"Looked up {done:,} pairs in {elapsed} ({self.requests:,} requests, {self.rate_limited} rate-limited).\n"
            f"  Matched {matched:,}: {fmt(methods)}.\n"
            f"  Unmatched {sum(reasons.values()):,}: {fmt(reasons)}.\n"
            f"  Flagged far_from_town: {far:,}.\n"
            f"  Files: {len(read_rows(out_path)):,} rows in {out_path}, "
            f"{len(read_rows(unmatched_path)):,} in {unmatched_path}."))
