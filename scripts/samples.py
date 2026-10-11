import json
from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"


def _sample_paths():
    return sorted(SAMPLES_DIR.glob("vr-*.json"))


def list_samples():
    return [path.stem.split("-", 2)[2] for path in _sample_paths()]


def sample_fetch_log(request_id):
    return next(SAMPLES_DIR.glob(f"{request_id.lower()}-*-fetch-log.csv"), None)


def load_sample(name):
    key = name.lower()
    for path in _sample_paths():
        prefix, number, short_name = path.stem.split("-", 2)
        if key in (short_name, f"{prefix}-{number}"):
            return json.loads(path.read_text())
    raise KeyError(f"no sample named {name!r}")
