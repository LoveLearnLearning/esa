from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
OUTPUTS_DIR = HERE / "outputs"

def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(value, ensure_ascii=False) + "\n")

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()

def run_dir(run_id: str) -> Path:
    p = OUTPUTS_DIR / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p

def config() -> dict:
    return load_json(DATA_DIR / "config.json")

def questions() -> list[dict]:
    return load_json(DATA_DIR / "questions.json")
