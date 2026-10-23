"""TEST ONLY Git/source/build fixtures; no credentials, npm or external API calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verification_context import assert_context, capture, tree_digest
from verify_web_build import validate


class VerificationContextTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="verification-context-test-only-", dir=ROOT / ".tmp")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.sources = {
            ".gitignore": b".env\n*.key\n.cache/\nnode_modules/\nartifacts/\napps/web/dist/\n",
            "backend/main.py": b"# TEST ONLY\nprint('test only')\n",
            "apps/web/src/App.vue": b"<template>TEST ONLY</template>\n",
            "packages/api-schema/schema.d.ts": b"// TEST ONLY schema\n",
            "deploy/Caddyfile": b"# TEST ONLY gateway\n",
            "scripts/check.py": b"# TEST ONLY check\n",
            "tests/test_example.py": b"# TEST ONLY test\n",
            "package.json": b'{"name":"test-only","private":true}\n',
            "package-lock.json": b'{"name":"test-only","lockfileVersion":3}\n',
            "playwright.config.ts": b"// TEST ONLY browser config\n",
            "docs/README.md": b"TEST ONLY documentation\n",
        }
        for name, data in self.sources.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for args in (("init", "-q"), ("add", "."),
                     ("-c", "user.name=TEST ONLY", "-c", "user.email=test@example.invalid", "commit", "-qm", "TEST ONLY fixture")):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        self.dist = self.repo / "apps/web/dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_bytes(b"<html>TEST ONLY production-shaped build</html>\n")
        (self.dist / "assets/app.js").write_bytes(b"// TEST ONLY compiled fixture\n")

    def record(self):
        record = {"status": "passed", "context": capture(self.repo), "web_build": tree_digest(self.dist)}
        destination = self.repo / "artifacts/web-builds/TEST-ONLY/build.json"
        destination.parent.mkdir(parents=True)
        destination.write_text(json.dumps(record), encoding="utf-8")
        self.pointer = self.repo / "artifacts/web-build.json"
        self.pointer.write_text(json.dumps({"record": destination.relative_to(self.repo).as_posix()}), encoding="utf-8")
        return record, destination

    def test_crlf_normalization_preserves_source_identity(self):
        before = capture(self.repo)
        (self.repo / "backend/main.py").write_bytes(self.sources["backend/main.py"].replace(b"\n", b"\r\n"))
        after = capture(self.repo)
        self.assertEqual(before["fingerprint"], after["fingerprint"])
        self.assertEqual(before["files"], after["files"])
        assert_context(before, after)

    def test_documentation_change_does_not_invalidate_business_evidence(self):
        before = capture(self.repo)
        (self.repo / "docs/README.md").write_text("TEST ONLY revised historical evidence notes", encoding="utf-8")
        (self.repo / "docs/untracked.md").write_text("TEST ONLY untracked documentation", encoding="utf-8")
        after = capture(self.repo)
        self.assertEqual(before["files"], after["files"])
        assert_context(before, after)

    def test_ignored_credentials_and_untracked_ignored_files_are_never_read(self):
        before = capture(self.repo)
        ignored = ["backend/.env", "backend/test-private.key", "backend/.cache/ignored.py", "apps/web/node_modules/ignored.js"]
        private_paths = set()
        for name in ignored:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("TEST ONLY PRIVATE VALUE; must not be read", encoding="utf-8")
            private_paths.add(path)
        original = Path.read_bytes
        def read(path):
            if path in private_paths:
                raise AssertionError("Ignored TEST ONLY credential or cache was read")
            return original(path)
        with patch.object(Path, "read_bytes", read):
            after = capture(self.repo)
        assert_context(before, after)
        self.assertTrue(private_paths.isdisjoint(self.repo / item["path"] for item in after["files"]))

    def test_business_scripts_tests_schema_gateway_and_locks_all_invalidate_old_evidence(self):
        baseline = capture(self.repo)
        for name in self.sources:
            if name.startswith("docs/") or name == ".gitignore":
                continue
            with self.subTest(path=name):
                path = self.repo / name
                try:
                    path.write_bytes(self.sources[name] + b"\nTEST ONLY changed\n")
                    current = capture(self.repo)
                    self.assertNotEqual(baseline["fingerprint"], current["fingerprint"])
                    with self.assertRaises(ValueError):
                        assert_context(baseline, current)
                finally:
                    path.write_bytes(self.sources[name])

    def test_new_untracked_business_file_and_deleted_tracked_file_change_identity(self):
        baseline = capture(self.repo)
        addition = self.repo / "backend/new_module.py"
        addition.write_text("# TEST ONLY new untracked business code", encoding="utf-8")
        current = capture(self.repo)
        self.assertIn("backend/new_module.py", [item["path"] for item in current["files"]])
        with self.assertRaises(ValueError):
            assert_context(baseline, current)
        addition.unlink()
        (self.repo / "scripts/check.py").unlink()
        with self.assertRaises(ValueError):
            assert_context(baseline, capture(self.repo))

    def test_missing_or_tampered_context_is_rejected(self):
        current = capture(self.repo)
        damaged = deepcopy(current)
        damaged["files"][0]["sha256"] = "0" * 64
        for context in (None, {}, {**current, "fingerprint": "0" * 64}, damaged):
            with self.subTest(context=context), self.assertRaises(ValueError):
                assert_context(context, current)

    def test_verified_build_record_validates_without_rebuilding_or_npm(self):
        record, _ = self.record()
        with patch("verify_web_build.build", side_effect=AssertionError("Validation must never rebuild")), \
             patch("verify_web_build.shutil.which", side_effect=AssertionError("Validation must not invoke npm")):
            self.assertEqual(validate(self.repo), record)
        self.assertFalse(any(item["path"].startswith("apps/web/dist/") for item in record["context"]["files"]))

    def test_source_change_rejects_an_unchanged_old_build_record(self):
        self.record()
        (self.repo / "apps/web/src/App.vue").write_text("<template>TEST ONLY changed</template>", encoding="utf-8")
        with self.assertRaises(ValueError):
            validate(self.repo)

    def test_dist_change_rejects_record_even_when_source_is_unchanged(self):
        record, _ = self.record()
        (self.dist / "assets/app.js").write_text("// TEST ONLY changed compiled artifact", encoding="utf-8")
        assert_context(record["context"], capture(self.repo))
        with self.assertRaises(ValueError):
            validate(self.repo)

    def test_build_file_names_and_missing_index_are_part_of_verification(self):
        original = tree_digest(self.dist)
        asset = self.dist / "assets/app.js"
        asset.rename(self.dist / "assets/renamed.js")
        self.assertNotEqual(original["fingerprint"], tree_digest(self.dist)["fingerprint"])
        (self.dist / "index.html").unlink()
        with self.assertRaises(ValueError):
            tree_digest(self.dist)

    def test_build_entries_use_case_sensitive_posix_order_for_mixed_case_asset_hashes(self):
        # TEST ONLY Vite-shaped names reproduce Windows Path's case-insensitive
        # ordering, which differs from the archive's POSIX string inventory.
        files = {
            "assets/index-DbXCfATh.js": b"// TEST ONLY mixed case JS hash\n",
            "assets/index-DL2Xdrmd.css": b"/* TEST ONLY mixed case CSS hash */\n",
            "assets/app.js": b"// TEST ONLY compiled fixture\n",
            "index.html": b"<html>TEST ONLY production-shaped build</html>\n",
        }
        for name, data in files.items():
            (self.dist / name).write_bytes(data)
        canonical = ["assets/app.js", "assets/index-DL2Xdrmd.css", "assets/index-DbXCfATh.js", "index.html"]
        result = tree_digest(self.dist)
        self.assertEqual(result["files"], [
            {"path": name, "bytes": len(files[name]), "sha256": hashlib.sha256(files[name]).hexdigest()}
            for name in canonical
        ])

    def test_build_symlink_entries_and_root_are_rejected_before_following(self):
        # Deterministic symlink metadata fault injection also runs on Windows
        # hosts whose user token cannot create real symbolic links.
        original = Path.is_symlink
        for target in (self.dist / "assets/app.js", self.dist):
            with self.subTest(target=target):
                def is_symlink(path):
                    return path == target or original(path)
                with patch.object(Path, "is_symlink", is_symlink), self.assertRaises(ValueError):
                    tree_digest(self.dist)

    def test_pointer_outside_build_records_is_rejected_without_reading_target(self):
        record, _ = self.record()
        outside = self.base / "outside.json"
        outside.write_text(json.dumps(record), encoding="utf-8")
        sibling = self.repo / "artifacts/web-builds-other/build.json"
        sibling.parent.mkdir()
        sibling.write_text(json.dumps(record), encoding="utf-8")
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path in {outside, sibling}:
                raise AssertionError("Outside build record must be rejected before reading")
            return original(path, *args, **kwargs)
        for name in (str(outside), "../outside.json", "artifacts/web-builds-other/build.json", "artifacts/web-builds/../../../outside.json"):
            self.pointer.write_text(json.dumps({"record": name}), encoding="utf-8")
            with self.subTest(pointer=name), patch.object(Path, "read_text", read), self.assertRaises(ValueError):
                validate(self.repo)

    def test_incomplete_build_record_cannot_be_used_as_passed_evidence(self):
        record, destination = self.record()
        for status in ("running", "failed", None):
            destination.write_text(json.dumps({**record, "status": status}), encoding="utf-8")
            with self.subTest(status=status), self.assertRaises(ValueError):
                validate(self.repo)


if __name__ == "__main__":
    unittest.main()
