"""Opt-in authorized integration verification. No fixtures or fallbacks."""
import argparse
import json
from pathlib import Path
import time

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://127.0.0.1:8000/api/v1/travel")
parser.add_argument("--city", required=True)
parser.add_argument("--keyword", required=True)
parser.add_argument("--date", required=True)
parser.add_argument("--output", default="artifacts/live-travel-verification.json")
args = parser.parse_args()

with httpx.Client(base_url=args.base, timeout=20) as client:
    capabilities = client.get("/capabilities").json()
    if not capabilities.get("configured"):
        raise SystemExit("Provider is not configured. No synthetic integration result will be generated.")
    created = client.post("/tasks", json={"city": args.city, "query": args.keyword,
        "start_date": args.date, "days": 1, "stops_per_day": 2, "stay_minutes": 60})
    created.raise_for_status()
    task_id = created.json()["id"]
    deadline = time.monotonic() + 210
    while time.monotonic() < deadline:
        response = client.get(f"/tasks/{task_id}")
        response.raise_for_status()
        task = response.json()
        if task["status"] not in {"queued", "running"}:
            break
        time.sleep(1)
    else:
        client.post(f"/tasks/{task_id}/cancel")
        raise SystemExit("Verification timed out; task cancellation requested")
    events = client.get(f"/tasks/{task_id}/events").json()
    if task["status"] != "succeeded":
        raise SystemExit(json.dumps({"task": task, "events": events}, ensure_ascii=False))
    response = client.get(f"/itineraries/{task['itinerary_id']}")
    response.raise_for_status()
    trip = response.json()
    assert all(stop["poi"]["source"]["provider"] == "amap" for day in trip["days"] for stop in day["stops"])
    assert all(stop["travel_to_next"]["source"]["provider"] == "amap" for day in trip["days"] for stop in day["stops"] if stop["travel_to_next"])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"live_provider": True, "task": task, "events": events, "itinerary": trip}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Authorized live verification passed: {output.resolve()}")
