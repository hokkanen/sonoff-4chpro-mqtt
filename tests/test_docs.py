"""Offline release documentation boundaries, using synthetic source dictionaries."""
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_docs import check_docs
from repo_tools import CheckError


def source():
    return {
        "project.json": json.dumps({"name": "sonoff-4chpro-mqtt", "version": "0.1.0", "license": "GPL-3.0-or-later", "protocolVersion": 1, "buildIdentity": "lease-test"}).encode(),
        "schemas/state.schema.json": json.dumps({"properties": {"build": {"const": "lease-test"}}}).encode(),
        "README.md": b"# Candidate 0.1.0\n[Protocol](docs/protocol.md#current-contract)\n",
        "CHANGELOG.md": b"# Changes\n## 0.1.0\n",
        "RELEASE_NOTES.md": b"# Version 0.1.0\n",
        "docs/protocol.md": b"# Current contract\n[Home](../README.md)\n",
    }


class DocumentationBoundaries(unittest.TestCase):
    def test_valid_local_paths_anchors_and_external_links(self):
        files = source()
        files["README.md"] += b"[External](https://example.invalid/)\n"
        self.assertEqual(check_docs(files), 4)

    def test_missing_target_or_anchor_rejected(self):
        for target in ("absent.md", "docs/protocol.md#absent", "../outside.md"):
            files = source()
            files["README.md"] += f"[Bad]({target})".encode()
            with self.subTest(target=target), self.assertRaises(CheckError):
                check_docs(files)

    def test_private_and_active_uri_schemes_rejected(self):
        for target in ("file:///example", "javascript:alert", "data:text/plain,example", "/example.md", "//example.invalid/file"):
            files = source()
            files["README.md"] += f"[Bad]({target})".encode()
            with self.subTest(target=target), self.assertRaises(CheckError):
                check_docs(files)

    def test_code_block_is_not_a_real_heading_or_link(self):
        files = source()
        files["README.md"] += b"\n```text\n[Example](absent.md)\n```\n"
        check_docs(files)
        files["docs/protocol.md"] += b"\n```text\n# Not a heading\n```\n"
        files["README.md"] += b"[Invalid](docs/protocol.md#not-a-heading)"
        with self.assertRaises(CheckError):
            check_docs(files)

    def test_unknown_or_inconsistent_release_metadata_rejected(self):
        for field, value in (("retired", True), ("version", "../0.1.0"), ("version", "00.1.0"), ("protocolVersion", True), ("license", "other"), ("buildIdentity", "different")):
            files = source()
            project = json.loads(files["project.json"])
            project[field] = value
            files["project.json"] = json.dumps(project).encode()
            with self.subTest(field=field, value=value), self.assertRaises(CheckError):
                check_docs(files)

    def test_stale_release_notes_rejected(self):
        files = source()
        files["RELEASE_NOTES.md"] = b"No current version"
        with self.assertRaises(CheckError):
            check_docs(files)

    def test_duplicate_source_metadata_is_not_silently_discarded(self):
        files = source()
        original = files["project.json"]
        files["project.json"] = b'{"version":"ignored-value",' + original[1:]
        with self.assertRaises(CheckError):
            check_docs(files)


if __name__ == "__main__":
    unittest.main()
