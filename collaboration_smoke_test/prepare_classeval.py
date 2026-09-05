"""Fetch the exact dataset pinned by the vendored Inspect ClassEval task.

Run with: uv run --with pyarrow python prepare_classeval.py
Dataset license: CC BY-NC 4.0; https://github.com/FudanSELab/ClassEval
"""
import hashlib
import json
import urllib.request
from pathlib import Path

import pyarrow.parquet as pq

BASE = Path(__file__).resolve().parent / "classeval" / "data"
REVISION = "fef204b34e221f207f47904ee660bb920d4c5d1d"
FILENAME = "test-00000-of-00001-5c45fa6e45572491.parquet"
SHA256 = "ac2f490a8fa0ca63d8b6d166821ca430a382dc04611209e2067a2714cc89df2a"

def main():
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "test.parquet"
    if not path.exists():
        url = f"https://huggingface.co/datasets/FudanSELab/ClassEval/resolve/{REVISION}/data/{FILENAME}"
        with urllib.request.urlopen(url, timeout=60) as response:
            path.write_bytes(response.read())
    if hashlib.sha256(path.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Dataset checksum mismatch")
    record = next(r for r in pq.read_table(path).to_pylist() if r["task_id"] == "ClassEval_39")
    (BASE / "ClassEval_39.json").write_text(json.dumps(record, indent=2))
    print(f"Prepared {record['task_id']}: {record['class_name']}")

if __name__ == "__main__":
    main()
