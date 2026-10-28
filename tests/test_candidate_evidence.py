"""TEST ONLY candidate evidence; no real browser, npm, Caddy, API or credentials.

Reports intentionally contain synthetic verification results to exercise the
gate's consistency rules. Archive metadata is not a signature or trust proof.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from browser_runs import case_keys
from package_release import build_release, normalized, verify_archive
from verification_context import capture, digest, fingerprint, tree_digest
from verify_candidate import verify


class CandidateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="candidate-evidence-test-only-", dir=ROOT / ".tmp")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        sources = {
            ".gitignore": b"artifacts/\napps/web/dist/\n.env\n*.key\n",
            "README.md": b"TEST ONLY candidate fixture\n",
            "backend/main.py": b"# TEST ONLY backend\n",
            "apps/web/src/App.vue": b"<template>TEST ONLY</template>\n",
            "packages/api-schema/openapi.json": b'{"info":{"title":"TEST ONLY"}}\n',
            "packages/api-schema/schema.d.ts": b"// TEST ONLY generated contract\n",
            "deploy/Caddyfile": b"# TEST ONLY gateway\n",
            "scripts/check.py": b"# TEST ONLY verification script\n",
            "tests/test_only.py": b"# TEST ONLY discovered Python suite\n",
            "package.json": b'{"name":"test-only","private":true}\n',
            "package-lock.json": b'{"name":"test-only","lockfileVersion":3}\n',
            "playwright.config.ts": b"// TEST ONLY test discovery config\n",
        }
        for name, data in sources.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        manifest = {"purpose": "source_inventory", "format_version": 1,
                    "text_normalization": "UTF-8 CRLF to LF; binary unchanged", "files": [
                        {"path": name, "bytes": len(normalized(data)), "sha256": digest(normalized(data))}
                        for name, data in sorted(sources.items())]}
        (self.repo / "PUBLISH_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
        for args in (("init", "-q"), ("add", "."),
                     ("-c", "user.name=TEST ONLY", "-c", "user.email=test@example.invalid", "commit", "-qm", "TEST ONLY fixture")):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        self.identifier = "TEST-ONLY-CANDIDATE"
        self.dist = self.repo / "apps/web/dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_bytes(b"<html>TEST ONLY compiled fixture</html>\n")
        (self.dist / "assets/app.js").write_bytes(b"// TEST ONLY compiled asset\n")
        self.context = capture(self.repo)
        self.web = tree_digest(self.dist)
        package = build_release(self.repo / "artifacts/releases/TEST-ONLY", self.dist, root=self.repo)
        self.original_archive = Path(package["archive"])
        self.archive_sequence = 0
        self.archive = self.archive_with()
        self.metadata = verify_archive(self.archive)
        self.archive_hash = digest(self.archive.read_bytes())
        self.repository_path = self.repo / "artifacts/repository-runs" / self.identifier / "report.json"
        self.write(self.repository_path, {
            "run_id": self.identifier, "status": "passed", "passed": True, "context": self.context,
            "schema_consistent": True, "services_stopped_gracefully": True,
            "python_suites": [{"path": "tests/test_only.py", "passed": 3}], "python": 3,
            "typescript": 2, "web_build": self.web,
        })
        for browser in ("chromium", "firefox", "webkit"):
            for suite in ("local", "auth", "resilience"):
                report = {"errors": [], "stats": {"unexpected": 0, "flaky": 0, "skipped": 0}, "suites": [
                    {"specs": [{"id": "TEST ONLY " + suite, "tests": [{"projectName": browser,
                        "status": "expected", "results": [{"status": "passed", "retry": 0}]}]}]}]}
                report_path = self.browser_path(browser, suite, "report.json")
                self.write(report_path, report)
                planned, _ = case_keys(report)
                self.write(self.browser_path(browser, suite), {
                    "run_id": self.identifier, "browser": browser, "suite": suite,
                    "complete_suite": True, "passed": True, "services_stopped_gracefully": True,"cleanup_completed":True,
                    "context": self.context, "planned_cases": planned, "passed_count": 1,
                    "report_sha256": digest(report_path.read_bytes()), "web_build": self.web,
                })
        self.runtime_path = self.repo / "artifacts/runtime/TEST-ONLY.json"
        self.write(self.runtime_path, {
            "passed": 4, "externalCalls": 0, "archive_sha256": self.archive_hash,
            "git_commit": self.metadata["git_commit"], "working_tree_dirty": False, "context": self.context,
        })
        for kind in ("deployment", "recovery"):
            common = {"run_id": self.identifier, "status": "passed", "context": self.context,
                "services_stopped_gracefully": True, "cleanup_completed": True, "context_unchanged": True,
                "services": [{"name": "TEST ONLY service", "returncode": 0, "forced": False}]}
            self.write(self.drill_path(kind, "run.json"), {**common, "kind": kind, "passed": True})
            self.write(self.drill_path(kind), {**common, "passed": 2,
                "checks": ["TEST ONLY TLS check", "TEST ONLY data isolation check"], "tlsVerification": True,
                "systemTrustModified": False, "externalCalls": 0, "web_build": self.web,
                "archive_sha256": self.archive_hash, "release_commit": self.metadata["git_commit"],
                "archive_source_fingerprint": self.context["fingerprint"]})

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def browser_path(self, browser="chromium", suite="local", name="run.json"):
        return self.repo / "artifacts/browser-runs" / self.identifier / browser / suite / name

    def drill_path(self, kind, name="report.json"):
        return self.repo / "artifacts/drill-runs" / self.identifier / kind / name

    def archive_with(self, mutate=None):
        """Rewrite only TEST ONLY bytes/metadata, recomputing consistency hashes.

        This deliberately supplies a self-consistent fixture, not a signature.
        The real verifier must still bind its source/Web to separate evidence.
        """
        with zipfile.ZipFile(self.original_archive) as source:
            payload = {name: source.read(name) for name in source.namelist()}
        metadata = json.loads(payload.pop("RELEASE.json"))
        if mutate:
            mutate(payload, metadata)
        metadata["files"] = [{"path": name, "bytes": len(data), "sha256": digest(data)} for name, data in sorted(payload.items())]
        web_files = [{**entry, "path": entry["path"][4:]} for entry in metadata["files"] if entry["path"].startswith("web/")]
        metadata["verification"] = {"context_fingerprint": self.context["fingerprint"], "web_fingerprint": fingerprint(web_files)}
        self.archive_sequence += 1
        path = self.repo / "artifacts/releases" / f"TEST-ONLY-{self.archive_sequence}.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for name, data in payload.items():
                target.writestr(name, data)
            target.writestr("RELEASE.json", json.dumps(metadata))
        verify_archive(path)
        return path

    def check(self, archive=None):
        return verify(self.identifier, archive or self.archive, self.runtime_path, root=self.repo)

    def rejected_mutation(self, path, mutate, message=None):
        original = self.read(path)
        changed = deepcopy(original)
        mutate(changed)
        self.write(path, changed)
        try:
            if message:
                with self.assertRaisesRegex(ValueError, message):
                    self.check()
            else:
                with self.assertRaises(ValueError):
                    self.check()
        finally:
            self.write(path, original)

    def test_complete_consistent_candidate_joins_all_exact_evidence(self):
        result = self.check()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["archive_sha256"], self.archive_hash)
        self.assertEqual(result["release_commit"], self.metadata["git_commit"])
        self.assertEqual(result["web_build"], self.web)
        self.assertEqual(result["repository_browser_executions"], 14)
        self.assertEqual(result["runtime_checks"], 4)
        self.assertEqual(result["drill_checks"], {"deployment": 2, "recovery": 2})
        self.assertEqual(len(result["evidence"]), 24)
        for item in result["evidence"]:
            self.assertEqual(item["sha256"], digest((self.repo / item["path"]).read_bytes()))

    def test_missing_or_old_context_at_each_boundary_is_rejected(self):
        paths = [self.repository_path, self.browser_path(), self.runtime_path,
                 self.drill_path("deployment", "run.json"), self.drill_path("recovery")]
        for path in paths:
            for mode in ("missing", "old"):
                with self.subTest(path=path.relative_to(self.repo), mode=mode):
                    def mutate(record):
                        if mode == "missing":
                            record.pop("context")
                        else:
                            record["context"]["fingerprint"] = "0" * 64
                    self.rejected_mutation(path, mutate, "different source")

    def test_repository_browser_and_https_must_verify_the_archive_web_bytes(self):
        for path in (self.repository_path, self.browser_path("firefox", "resilience"), self.drill_path("deployment")):
            with self.subTest(path=path.relative_to(self.repo)):
                def mutate(record):
                    record["web_build"]["files"][0]["sha256"] = "0" * 64
                    record["web_build"]["fingerprint"] = fingerprint(record["web_build"]["files"])
                self.rejected_mutation(path, mutate, "Web")

    def test_self_consistent_archive_with_different_actual_web_bytes_is_rejected(self):
        def mutate(payload, _metadata):
            payload["web/assets/app.js"] = b"// TEST ONLY stale but self-consistent compiled bytes\n"
        archive = self.archive_with(mutate)
        self.assertNotEqual(digest(archive.read_bytes()), self.archive_hash)
        with self.assertRaisesRegex(ValueError, "Archive Web differs"):
            self.check(archive)

    def test_runtime_and_recovery_must_match_the_exact_archive_hash(self):
        for path in (self.runtime_path, self.drill_path("recovery")):
            with self.subTest(path=path.relative_to(self.repo)):
                self.rejected_mutation(path, lambda record: record.update(archive_sha256="0" * 64), "another archive")
        self.rejected_mutation(self.drill_path("recovery"),
            lambda record: record.update(archive_source_fingerprint="0" * 64), "another archive")

    def test_missing_browser_scope_and_incomplete_failed_or_forced_cleanup_are_rejected(self):
        missing = self.browser_path("webkit", "auth", "report.json")
        original = missing.read_bytes()
        missing.unlink()
        try:
            with self.assertRaises(OSError):
                self.check()
        finally:
            missing.write_bytes(original)
        cases = [
            (self.browser_path(), lambda record: record.update(complete_suite=False)),
            (self.browser_path(), lambda record: record.update(services_stopped_gracefully=False)),
            (self.browser_path(), lambda record: record.update(cleanup_completed=False)),
            (self.drill_path("recovery", "run.json"), lambda record: record.update(cleanup_completed=False)),
            (self.drill_path("deployment"), lambda record: record.update(status="failed")),
            (self.drill_path("deployment"), lambda record: record["services"][0].update(forced=True)),
            (self.drill_path("recovery"), lambda record: record["services"][0].update(returncode=1)),
        ]
        for path, mutate in cases:
            with self.subTest(path=path.relative_to(self.repo), mutate=mutate):
                self.rejected_mutation(path, mutate)

    def test_undiscovered_duplicate_and_missing_python_suites_cannot_satisfy_repository_gate(self):
        def invented(record):
            record["python_suites"].append({"path": "tests/not_discovered.py", "passed": 1})
            record["python"] += 1
        def duplicated(record):
            record["python_suites"].append(deepcopy(record["python_suites"][0]))
            record["python"] *= 2
        for mutate in (invented, duplicated, lambda record: record.update(python_suites=[], python=0)):
            with self.subTest(mutate=mutate):
                self.rejected_mutation(self.repository_path, mutate, "Repository evidence is incomplete")

    def test_dirty_archive_is_rejected_even_with_valid_integrity_hashes(self):
        archive = self.archive_with(lambda _payload, metadata: metadata.update(working_tree_dirty=True))
        with self.assertRaisesRegex(ValueError, "clean commit"):
            self.check(archive)

    def test_browser_report_tampering_is_rejected_before_self_reported_counts(self):
        path = self.browser_path("firefox", "local", "report.json")
        # A harmless stats field leaves the cases passing but changes exact
        # report bytes. Count-only validation must not accept the modification.
        self.rejected_mutation(path, lambda record: record["stats"].update(duration=999), "report changed")


if __name__ == "__main__":
    unittest.main()
