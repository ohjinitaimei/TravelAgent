"""Opt-in live model + HTTP clarification verification through Web's proxy.

No Amap calls, synthetic POIs, planning tasks or itineraries are created.
"""
import argparse
import json
from pathlib import Path
import time

import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--allow-model-call",action="store_true",required=True)
    parser.add_argument("--base",default="http://127.0.0.1:5173/api/v1/travel")
    parser.add_argument("--reference-date",required=True)
    parser.add_argument("--date",required=True)
    parser.add_argument("--city",default="杭州")
    parser.add_argument("--output",default="artifacts/live-clarification-verification.json")
    args=parser.parse_args()
    with httpx.Client(base_url=args.base,timeout=20) as client:
        capability=client.get("/capabilities").raise_for_status().json()
        if not all(capability.get(key) for key in ("draft_enabled","llm_configured","helloagents_available")):
            raise SystemExit("Live intake is not enabled/configured; no verification result created")
        before=client.get("/itineraries").raise_for_status().json()
        task=client.post("/drafts",json={"text":"想逛博物馆，需要提前预约。","reference_date":args.reference_date}).raise_for_status().json()
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            task=client.get("/tasks/"+task["id"]).raise_for_status().json()
            if task["status"] not in {"queued","running"}: break
            time.sleep(.3)
        else:
            client.post("/tasks/"+task["id"]+"/cancel")
            raise SystemExit("Intake verification timed out; cancellation requested")
        if task["status"]!="succeeded": raise SystemExit(json.dumps(task,ensure_ascii=True))
        url="/drafts/"+task["draft_id"]
        initial=client.get(url).raise_for_status().json()
        assert initial["proposal"]["values"]["city"] is None
        assert initial["proposal"]["values"]["start_date"] is None
        assert initial["questions"]
        first=client.patch(url,json={"expected_revision":initial["revision"],"values":{"city":args.city},"confirm_fields":["query"]}).raise_for_status().json()
        second=client.patch(url,json={"expected_revision":first["revision"],"values":{"start_date":args.date,"budget":0}}).raise_for_status().json()
        assert second["id"]==initial["id"]
        assert second["revision"]==initial["revision"]+2
        assert second["proposal"]["values"]["city"]==args.city
        assert {"city","query","start_date","budget"}<=set(second["confirmed_fields"])
        assert second["proposal"]["values"]["budget"]==0
        assert second["questions"]==[]
        assert second["proposal"]["unhandled_requirements"]==initial["proposal"]["unhandled_requirements"]
        stale=client.patch(url,json={"expected_revision":first["revision"],"values":{"city":"上海"}})
        assert stale.status_code==409
        assert stale.json()["error"]["code"]=="draft_revision_conflict"
        assert client.get(url).raise_for_status().json()==second
        assert client.get("/itineraries").raise_for_status().json()==before
        assert client.get("/tasks/"+task["id"]).raise_for_status().json()==task
        result={"live_model":True,"via_web_proxy":True,"browser_interaction_verified":False,
            "task":task,"initial":initial,"first":first,"second":second,"stale_error":stale.json(),
            "events":client.get("/tasks/"+task["id"]+"/events").raise_for_status().json(),
            "itinerary_count":len(before["items"])}
        output=Path(args.output)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"Live clarification HTTP verification passed: {output.resolve()}")


if __name__=="__main__":
    main()
