"""Sends out/imagery.json to the Agronomicon API (POST /imagery/import), which stores it in the database.
The API's own daily run does this by itself; this is for a run by hand. Sending the same file again changes
nothing. Standard library only, so any Python can run it.

    python push.py
    python push.py --api http://localhost:8000 --file out/imagery.json
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--file", type=Path, default=HERE / "out" / "imagery.json")
    args = parser.parse_args()

    body = args.file.read_bytes()
    request = urllib.request.Request(f"{args.api.rstrip('/')}/imagery/import", method="POST", data=body,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            answer = json.loads(response.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        sys.exit(f"API not reachable at {args.api}: {e}")
    data = json.loads(body)
    print(f"sent {len(data['results'])} results and {len(data['skipped'])} skipped scenes; "
          f"{answer['newScenes']} were new")


if __name__ == "__main__":
    main()
