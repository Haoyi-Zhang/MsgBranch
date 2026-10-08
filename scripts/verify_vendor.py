"""Verify exact Fluent source bytes and the explicitly adapted Weblate excerpt."""
from pathlib import Path
import hashlib
import json
ROOT = Path(__file__).resolve().parents[1]

def run():
    p = ROOT / "vendor/python-fluent"
    manifest = json.loads((p / "PROVENANCE.json").read_text())
    for row in manifest["upstream_files"]:
        raw = (p / row["local"]).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if actual != row["git_blob_sha1"]:
            raise ValueError(f"Upstream source integrity mismatch: {row['local']}")
    w = ROOT / "vendor/weblate-format-core"
    expected = json.loads((w / "PROVENANCE.json").read_text())["local_sha256"]
    if hashlib.sha256((w / "format_core.py").read_bytes()).hexdigest() != expected:
        raise ValueError("Weblate local excerpt integrity mismatch")
    lh = ROOT / "vendor/localhero"
    lhp = json.loads((lh / "PROVENANCE.json").read_text())
    for name, expected in lhp["local_sha256"].items():
        if hashlib.sha256((lh / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"LocalHero component integrity mismatch: {name}")
    print(f"Verified {len(manifest['upstream_files'])} exact upstream Fluent files, the adapted Weblate excerpt, and the versioned LocalHero source component")

if __name__ == "__main__":
    run()
