"""Verify retained input bytes and study implementation receipts, without network."""
from pathlib import Path
import hashlib
import json
ROOT = Path(__file__).resolve().parents[1]

def check(path, expected, *, git_blob=False):
    raw = path.read_bytes()
    actual = (hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
              if git_blob else hashlib.sha256(raw).hexdigest())
    if actual != expected:
        raise ValueError(f"Retained input differs: {path.relative_to(ROOT)}")

def run():
    sph = ROOT / "data/upstream/sphinx"
    for name, expected in json.loads((sph / "PROVENANCE.json").read_text())["retained_sha256"].items():
        check(sph / name, expected)
    j = ROOT / "data/upstream/jupyter"
    jp = json.loads((j / "PROVENANCE.json").read_text())
    check(j / "running_server_info.py", jp["source_method_sha256"])
    check(j / "notebook.po", jp["original_catalog_sha256"])
    oh = ROOT / "data/openhangar"
    for name, expected in json.loads((oh / "PROVENANCE.json").read_text())["local_sha256"].items():
        check(oh / name, expected)
    bed = ROOT / "data/bedrock"
    bp = json.loads((bed / "PROVENANCE.json").read_text())
    for row in bp["upstream_files"]:
        check(bed / row["local"], row["git_blob_sha1"], git_blob=True)
        check(bed / row["local"], row["sha256"])
    check(bed / "boundary.py", bp["boundary_sha256"])
    xrpl = ROOT / "data/xrpldashboard"
    for name in ("before.jinja", "after.jinja", "LICENSE", "PROVENANCE.json"):
        if not (xrpl / name).is_file() or (xrpl / name).stat().st_size == 0:
            raise ValueError(f"Missing xrpldashboard input: {name}")
    screen = json.loads((ROOT / "corpus/public-fix-screen.json").read_text())
    if len(screen) != 20 or len({row["case_id"] for row in screen}) != 20:
        raise ValueError("Public-fix screen identity mismatch")
    for study, generator in [("validation", "partition_evaluate.py"), ("confirmation", "partition_confirm.py")]:
        protocol = json.loads((ROOT / "data" / study / "protocol.json").read_text())
        for name, expected in protocol["implementation_sha256"].items():
            check(ROOT / "src/msgbranch" / name, expected)
        check(ROOT / "scripts" / generator, protocol["generator_sha256"])
    print("Verified retained application inputs, five exact Bedrock files, the 20-lead public-fix ledger, and two implementation/generator receipts")

if __name__ == "__main__":
    run()
