import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from repo_tools import (CheckError, archive_files, check_content, external_path,
                        file_sha256, safe_name, sha256, source_digest,
                        verify_build_bundle, write_source_archive)
from build import extract_archive, verify_archive


class SourceBoundaries(unittest.TestCase):
    def test_paths_and_artifacts_fail_closed(self):
        for name in ("../escape", "/escape", "a\\escape", "private/settings.json", "captures/events.json", "firmware.bin", ".git/config", "settings-backup.json"):
            with self.subTest(name=name), self.assertRaises(CheckError):
                safe_name(name)

    def test_secret_indicators_and_network_identity_are_rejected(self):
        fixtures = ["-" * 5 + "BEGIN PRIVATE KEY" + "-" * 5, "mqtt" + "://owner:password@broker", ".".join(["192", "168", "2", "9"]), ":".join(["DE", "AD", "BE", "EF", "12", "34"])]
        for value in fixtures:
            with self.subTest(kind=value[:4]), self.assertRaises(CheckError):
                check_content("example.txt", value.encode())
        check_content("example.txt", b"http://192.0.2.20/ AA:BB:CC:DD:EE:FF section 3.3.1.3")

    def test_checkout_and_other_git_ancestor_rejected(self):
        root = Path(__file__).resolve().parents[1]
        with self.assertRaises(CheckError):
            external_path(root / "unused-build")
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / ".git").mkdir()
            with self.assertRaises(CheckError):
                external_path(folder / "build")

    def test_source_archive_roundtrip_and_duplicate_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.tar.gz"
            files = {"README.md": b"Synthetic source\n", "src/gate.h": b"// GPL\n"}
            write_source_archive(archive, files)
            self.assertEqual(archive_files(archive), files)
            repeated = Path(directory) / "repeated.tar.gz"
            write_source_archive(repeated, files)
            self.assertEqual(repeated.read_bytes(), archive.read_bytes())
            with self.assertRaises(FileExistsError):
                write_source_archive(archive, files)
            duplicate = Path(directory) / "duplicate.tar.gz"
            with tarfile.open(duplicate, "w:gz") as stream:
                for _ in range(2):
                    info = tarfile.TarInfo("a.txt"); info.size = 1
                    stream.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(CheckError):
                archive_files(duplicate)


class UpstreamInput(unittest.TestCase):
    commit = "f" * 40

    def archive(self, path, name, kind=tarfile.REGTYPE):
        with tarfile.open(path, "w:gz") as archive:
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind == tarfile.REGTYPE:
                info.size = 4; archive.addfile(info, io.BytesIO(b"test"))
            else:
                info.linkname = "outside"; archive.addfile(info)

    def test_hash_and_size_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "upstream.tar.gz"
            path.write_bytes(b"synthetic upstream")
            lock = {"archiveBytes": path.stat().st_size, "archiveSha256": file_sha256(path)}
            verify_archive(path, lock)
            path.write_bytes(b"changed upstream")
            with self.assertRaises(CheckError):
                verify_archive(path, lock)

    def test_extraction_rejects_traversal_links_and_wrong_root(self):
        names = [("Tasmota-" + self.commit + "/../escape", tarfile.REGTYPE),
                 ("Tasmota-" + self.commit + "/link", tarfile.SYMTYPE),
                 ("Tasmota-" + self.commit + "/hardlink", tarfile.LNKTYPE),
                 ("unexpected/source.txt", tarfile.REGTYPE),
                 ("Tasmota-" + self.commit + "/fifo", tarfile.FIFOTYPE)]
        with tempfile.TemporaryDirectory() as directory:
            for index, (name, kind) in enumerate(names):
                path = Path(directory) / f"bad-{index}.tar.gz"
                output = Path(directory) / f"out-{index}"; output.mkdir()
                self.archive(path, name, kind)
                with self.subTest(kind=index), self.assertRaises(CheckError):
                    extract_archive(path, output, self.commit)

    def test_extraction_keeps_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "upstream.tar.gz"
            output = Path(directory) / "output"; output.mkdir()
            self.archive(path, "Tasmota-" + self.commit + "/source.txt")
            extract_archive(path, output, self.commit)
            self.assertEqual((output / "source.txt").read_bytes(), b"test")


class ArtifactBundle(unittest.TestCase):
    def fixture(self, directory):
        import gzip
        upstream = b"synthetic upstream source"
        lock = {"commit": "f" * 40, "archiveBytes": len(upstream), "archiveSha256": sha256(upstream), "platformioVersion": "6.1.19"}
        project = {"name": "synthetic-firmware", "version": "0.1.0"}
        files = {"upstream.lock.json": json.dumps(lock).encode(), "project.json": json.dumps(project).encode(),
                 "firmware/source-manifest.json": b'{"sha256":{}}', "LICENSE": b"GPL-3.0-or-later", "NOTICE": b"Synthetic fixture"}
        upstream_name = "Tasmota-" + lock["commit"] + ".tar.gz"
        binary = b"\xe9\x01\x03\x20synthetic-not-real-firmware"
        (directory / "sonoff4chpro-lease.bin").write_bytes(binary)
        (directory / "sonoff4chpro-lease.bin.gz").write_bytes(gzip.compress(binary, mtime=0))
        (directory / upstream_name).write_bytes(upstream)
        write_source_archive(directory / "project-source.tar.gz", files)
        for name in ("LICENSE", "NOTICE"):
            (directory / name).write_bytes(files[name])
        manifest = {"project": project, "upstream": lock, "projectSha256": source_digest(files),
                    "platformioVersion": "6.1.19", "sourceBundle": ["project-source.tar.gz", upstream_name],
                    "flash": {"mode": "dout", "frequencyMHz": 40, "sizeBytes": 1048576},
                    "files": {p.name: {"sha256": file_sha256(p), "bytes": p.stat().st_size} for p in directory.iterdir()}}
        (directory / "build-manifest.json").write_text(json.dumps(manifest))
        return files, manifest

    def test_bundle_roundtrip_and_tampered_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            files, _manifest = self.fixture(directory)
            verify_build_bundle(directory, files, match_tree=True)
            (directory / "sonoff4chpro-lease.bin").write_bytes(b"changed")
            with self.assertRaises(CheckError):
                verify_build_bundle(directory, files)

    def test_bundle_extra_artifact_and_wrong_source_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            files, manifest = self.fixture(directory)
            extra = directory / "unreviewed.txt"; extra.write_text("unexpected")
            with self.assertRaises(CheckError):
                verify_build_bundle(directory, files)
            extra.unlink()
            manifest["projectSha256"] = "0" * 64
            (directory / "build-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(CheckError):
                verify_build_bundle(directory, files)

    def test_bundle_unknown_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            files, manifest = self.fixture(directory)
            manifest["unexpectedMetadata"] = "unreviewed"
            (directory / "build-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(CheckError):
                verify_build_bundle(directory, files)
