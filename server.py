#!/usr/bin/env python3
import sys, os
from pathlib import Path

# Add repo to sys.path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import argparse
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AZOTH Local Agent Server")
    parser.add_argument("--port", type=int, default=8136)
    parser.add_argument("--host", default="127.0.0.1")
    args, _ = parser.parse_known_args()
    uvicorn.run("web_ui:app", host=args.host, port=args.port, log_level="info")
