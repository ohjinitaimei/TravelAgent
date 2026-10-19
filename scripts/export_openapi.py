from pathlib import Path
import json
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from main import app

schema = app.openapi()
# Export only the new travel contract. Legacy endpoints remain in /openapi.json.
schema["paths"] = {path: item for path, item in schema["paths"].items() if path.startswith("/api/v1/travel")}
models = schema.get("components", {}).get("schemas", {})
needed = set()

def refs(value):
    if isinstance(value, dict):
        reference = value.get("$ref", "")
        if reference.startswith("#/components/schemas/"):
            name = reference.rsplit("/", 1)[-1]
            if name not in needed:
                needed.add(name)
                refs(models.get(name, {}))
        for item in value.values():
            refs(item)
    elif isinstance(value, list):
        for item in value:
            refs(item)

refs(schema["paths"])
schema["components"]["schemas"] = {name: item for name, item in models.items() if name in needed}
target = root / "packages" / "api-schema" / "openapi.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Exported {len(schema['paths'])} travel paths to {target}")
