"""Reproducible LF-normalized source inventory; excludes ignored files and itself."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/"PUBLISH_MANIFEST.json"


def inventory():
    candidates=subprocess.check_output(["git","ls-files","-z","--cached","--others","--exclude-standard"],cwd=ROOT).decode("utf-8").split("\0")
    files=[]
    for name in sorted(set(candidates)):
        if not name or name==MANIFEST.name: continue
        source=ROOT/name
        if source.is_symlink(): raise SystemExit("Review symlink before publication: "+name)
        if not source.is_file(): continue
        data=source.read_bytes()
        if b"\0" not in data[:8000]:
            try: data=data.decode("utf-8").replace("\r\n","\n").encode("utf-8")
            except UnicodeError: pass
        files.append({"path":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()})
    return {"purpose":"source_inventory","format_version":1,"text_normalization":"UTF-8 CRLF to LF; binary unchanged", "files":files}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    value=inventory()
    if args.check:
        if not MANIFEST.exists() or json.loads(MANIFEST.read_text(encoding="utf-8"))!=value:
            raise SystemExit("Source inventory differs. Run python scripts/update_publish_manifest.py and commit the result.")
        print(f"Source inventory verified: {len(value['files'])} files.")
    else:
        MANIFEST.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(f"Source inventory updated: {len(value['files'])} files.")


if __name__=="__main__": main()
