"""
«DataLoader» (new, approved in PLAN §8) — the start-up import, run as one command.

Runs the PLAN §3.4 steps in order. Missing raw files are downloaded first. Step 5 is
optional: pass --coords <csv> for real coordinates, or --approximate for the dev-only
town-centroid fallback. Every step is safe to re-run.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run the whole import pipeline (PLAN §3.4)."

    def add_arguments(self, parser):
        step5 = parser.add_mutually_exclusive_group()
        step5.add_argument("--coords", metavar="CSV", help="Coordinates CSV for import_flat_coordinates.")
        step5.add_argument("--approximate", action="store_true",
                           help="DEV ONLY: put flats without coordinates at their town centre.")
        parser.add_argument("--no-download", action="store_true", help="Don't fetch missing raw files.")

    def handle(self, *args, coords=None, approximate=False, no_download=False, **options):
        if not no_download:
            call_command("download_datasets", stdout=self.stdout, stderr=self.stderr)
        steps = [("import_towns",), ("import_flats",), ("import_transport",), ("import_amenities",)]
        if coords:
            steps.append(("import_flat_coordinates", coords))
        elif approximate:
            steps.append(("assign_approximate_coords",))
        steps.append(("compute_proximity",))

        for number, (name, *args_) in enumerate(steps, start=1):
            self.stdout.write(self.style.MIGRATE_HEADING(f"[{number}/{len(steps)}] {name}"))
            try:
                call_command(name, *args_, stdout=self.stdout, stderr=self.stderr)
            except CommandError as exc:
                raise CommandError(f"{name} failed: {exc}")
        self.stdout.write(self.style.SUCCESS("Import complete."))
