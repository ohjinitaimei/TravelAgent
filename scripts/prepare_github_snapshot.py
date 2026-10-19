"""Export a reviewed development snapshot without touching the original Git history."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
EXCLUDED={"backend/pois.json","backend/pois.amap.enriched.json","backend/pois.amap.report.json",
          ".vscode/settings.json","adb.ps1","flutter.ps1"}
ROOT_FILES={"README.md","NOTICE.md",".gitignore",".gitattributes",".metadata","pubspec.yaml","pubspec.lock",
            "analysis_options.yaml","package.json","package-lock.json"}
DIRECTORIES={".github","apps","backend","docs","lib","android","windows","test","tests","scripts","packages"}
FORBIDDEN_PARTS={".git","node_modules",".venv","__pycache__",".cache",".tmp","artifacts","data"}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default=".tmp/github-release/TravelAgent")
    args=parser.parse_args()
    output=(ROOT/args.output).resolve()
    export_root=(ROOT/".tmp").resolve()
    if not output.is_relative_to(export_root) or output==export_root:
        raise SystemExit("Snapshot destination must be a new directory inside this workspace's .tmp")
    if output.exists():
        raise SystemExit("Destination already exists; choose a new name. Existing work is never deleted.")
    candidates=subprocess.check_output(["git","ls-files","-z","--cached","--others","--exclude-standard"],cwd=ROOT).decode("utf-8").split("\0")
    files=[]
    for name in sorted(set(candidates)):
        if not name or name in EXCLUDED: continue
        relative=Path(name)
        if any(part in FORBIDDEN_PARTS for part in relative.parts): continue
        if name not in ROOT_FILES and relative.parts[0] not in DIRECTORIES: continue
        if relative.name.startswith(".env") and relative.name!=".env.example": continue
        source=ROOT/relative
        if source.is_symlink(): raise SystemExit("Symlink requires explicit publication review: "+name)
        if not source.is_file(): continue
        data=source.read_bytes()
        if b"\0" not in data[:8000]:
            try:
                data=data.decode("utf-8").replace("\r\n","\n").encode("utf-8")
            except UnicodeError:
                pass
        files.append((name,data))
    output.mkdir(parents=True)
    manifest=[]
    for name,data in files:
        destination=output/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(data)
        manifest.append({"path":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()})
    report={"status":"development_not_production_ready","source_base_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "includes_working_tree_changes":True,"history_exported":False,"excluded_existing_files":sorted(EXCLUDED),"files":manifest}
    (output/"PUBLISH_MANIFEST.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"snapshot":str(output),"file_count":len(files)+1,"bytes":sum(len(data) for _,data in files)},ensure_ascii=True))


if __name__=="__main__":
    main()
