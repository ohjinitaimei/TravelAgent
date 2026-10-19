"""Test-owned API process with file-based graceful shutdown; not a production entrypoint."""
import argparse
from pathlib import Path
import sys
import threading
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,required=True)
    parser.add_argument("--stop-file",type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root/"backend"))
    import uvicorn
    server=uvicorn.Server(uvicorn.Config("main:app",host="127.0.0.1",port=args.port))
    def stop_when_requested():
        while not args.stop_file.exists(): time.sleep(.1)
        server.should_exit=True
    threading.Thread(target=stop_when_requested,daemon=True).start()
    server.run()


if __name__=="__main__":
    main()
