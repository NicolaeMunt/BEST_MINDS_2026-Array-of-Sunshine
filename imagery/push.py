"""Sends the analysed scenes from out/imagery.json to the Crop Monitor API, which shows the latest
one per parcel and serves the overlay images. Standard library only, so any Python can run it.

    python push.py                       # demo1 -> P4 on http://localhost:8000
    python push.py --map demo1=P4 --api http://localhost:8000
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# imagery parcel_id -> API parcel ID. Parcels not listed keep their own ID.
DEFAULT_MAP = {"demo1": "P4"}


def post(url, body):
    request = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--file", type=Path, default=HERE / "out" / "imagery.json")
    parser.add_argument("--map", action="append", default=[], metavar="IMAGERY_ID=API_ID")
    args = parser.parse_args()

    id_map = {**DEFAULT_MAP, **dict(m.split("=", 1) for m in args.map)}
    results = json.loads(args.file.read_text(encoding="utf-8"))["results"]

    sent = {}
    # Oldest first, so the API ends up with the whole season and the newest scene as the latest.
    for result in sorted(results, key=lambda r: r["scene_date"]):
        parcel_id = id_map.get(result["parcel_id"], result["parcel_id"])
        body = {k: v for k, v in result.items() if k != "parcel_id"}
        try:
            post(f"{args.api.rstrip('/')}/parcels/{parcel_id}/imagery", body)
        except urllib.error.HTTPError as e:
            sys.exit(f"{parcel_id} {result['scene_date']}: HTTP {e.code} {e.read().decode(errors='replace')[:200]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            sys.exit(f"API not reachable at {args.api}: {e}")
        sent[parcel_id] = sent.get(parcel_id, 0) + 1

    for parcel_id, count in sent.items():
        print(f"{parcel_id}: {count} scenes sent")


if __name__ == "__main__":
    main()
