"""Explicit, single real model request; never queries travel data or saves a trip."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-model-call", action="store_true", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--reference-date", required=True)
    parser.add_argument("--output", default="artifacts/live-intake-verification.json")
    args = parser.parse_args()
    # Use the same existing env loader as the API. No credentials are printed.
    from core.llm_intent_client import _load_env_file
    _load_env_file()
    from agent.travel_intake import create_draft
    from travel.provider import TravelFailure
    from travel.schemas import DraftRequest
    events = []
    try:
        request = DraftRequest(text=args.text, reference_date=args.reference_date)
        draft = create_draft(request, lambda stage, message: events.append({"stage": stage, "message": message}))
    except TravelFailure as error:
        print(json.dumps({"success": False, "code": error.code, "message": error.message}, ensure_ascii=False))
        return 1
    except Exception:
        print(json.dumps({"success": False, "code": "verification_failed"}))
        return 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"live_model": True, "travel_provider_called": False,
        "events": events, "draft": draft.model_dump(mode="json")}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Single live intake call passed: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
