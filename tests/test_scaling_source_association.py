"""Small retained-source binding regressions; no scanner/timing driver runs."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("retained_scaling_audit", ROOT/"scripts/audit_results.py")
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class RetainedScalingSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="retained-scaling-binding-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.receipt=json.loads((ROOT/"results/project-scaling.json").read_text(encoding="utf-8"))
        paths={x["path"] for x in self.receipt["source_identity"].values()}
        for row in self.receipt["records"]:
            paths.update(x["path"] for x in row["fixture_identity"].values())
        paths.update(("results/project-scaling.json",
                      "scripts/provenance/project-scaling-source.py",
                      "scripts/provenance/project-scaling-association.json"))
        for relative in paths:
            dest=self.root/relative
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/relative,dest)
    def check(self, receipt=None):
        return audit.audit_project_scaling(self.receipt if receipt is None else receipt,root=self.root)
    def test_valid_retained_source_is_distinct_from_current_measurement(self):
        actual=self.check()
        self.assertTrue(actual["captured_measured_source"])
        self.assertEqual(actual["observations_recounted"],24)
        self.assertIn("not remeasured",actual["scope"])
    def test_unreviewed_current_source_rejected(self):
        p=self.root/"src/msgbranch/project.py"
        p.write_bytes(p.read_bytes()+b"\n# owned tamper fixture\n")
        with self.assertRaisesRegex(ValueError,"unreviewed current"):self.check()
    def test_captured_source_tamper_rejected(self):
        p=self.root/"scripts/provenance/project-scaling-source.py"
        p.write_bytes(p.read_bytes()+b"\n# owned tamper fixture\n")
        with self.assertRaisesRegex(ValueError,"bound file bytes"):self.check()
    def test_association_tamper_rejected(self):
        p=self.root/"scripts/provenance/project-scaling-association.json"
        x=json.loads(p.read_text());x["scope"]="current timing"
        p.write_text(json.dumps(x),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"association changed"):self.check()
    def test_missing_association_rejected(self):
        (self.root/"scripts/provenance/project-scaling-association.json").unlink()
        with self.assertRaisesRegex(ValueError,"association missing"):self.check()
    def test_retained_receipt_bytes_cannot_be_resealed(self):
        p=self.root/"results/project-scaling.json"
        p.write_bytes(p.read_bytes()+b"\n")
        with self.assertRaisesRegex(ValueError,"receipt bytes"):self.check()
    def test_mutated_raw_observation_cannot_join_retained_receipt(self):
        x=copy.deepcopy(self.receipt);x["records"][0]["raw"][0]["wall_ms"]+=1
        with self.assertRaisesRegex(ValueError,"receipt content"):self.check(x)
    def test_unmodified_measured_source_still_must_match(self):
        p=self.root/"src/msgbranch/runtime.py";p.write_bytes(p.read_bytes()+b"\n")
        with self.assertRaisesRegex(ValueError,"bound file bytes"):self.check()
    def test_input_identity_remains_enforced(self):
        p=self.root/self.receipt["records"][0]["fixture_identity"]["source"]["path"]
        p.write_bytes(p.read_bytes()+b"\n")
        with self.assertRaisesRegex(ValueError,"bound file bytes"):self.check()
    def test_current_direct_receipt_does_not_need_historical_association(self):
        # The actual historical/current distinction is source bytes, not a
        # claim that every future measurement must use this captured source.
        original=(self.root/"scripts/provenance/project-scaling-source.py").read_bytes()
        (self.root/"src/msgbranch/project.py").write_bytes(original)
        (self.root/"scripts/provenance/project-scaling-association.json").unlink()
        self.assertFalse(self.check()["captured_measured_source"])

if __name__=="__main__":unittest.main()
