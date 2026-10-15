"""Synthetic dependency archive boundaries; never downloads or reads live data."""
import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dependencies import (apply_dependency_overrides, cached_dependencies,
                          dependency_specs, verify_dependency_archive)
from repo_tools import CheckError


class DependencyBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dependency-test-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, additions=(), missing_notice=False):
        path = self.root / "framework.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Core/package.json", json.dumps({"name": "framework-arduinoespressif8266", "version": "2.7.8"}))
            if not missing_notice:
                archive.writestr("Core/LICENSE", "Synthetic test license text")
            for name, data in additions:
                archive.writestr(name, data)
        return path, {"id": "framework", "package": "framework-arduinoespressif8266", "version": "2.7.8",
                      "file": path.name, "url": "https://github.com/tasmota/Arduino/releases/download/2.7.8/test.zip",
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
                      "root": "Core", "metadata": "package.json", "notices": ["LICENSE"]}

    def test_valid_source_metadata_and_notices(self):
        path, spec = self.archive()
        verify_dependency_archive(path, spec)

    def test_modified_digest_size_and_identity_fail(self):
        path, spec = self.archive()
        for field, value in (("bytes", 1), ("sha256", "0" * 64), ("version", "other"), ("package", "other")):
            with self.subTest(field=field), self.assertRaises(CheckError):
                verify_dependency_archive(path, dict(spec, **{field: value}))

    def test_required_notice_cannot_be_omitted(self):
        path, spec = self.archive(missing_notice=True)
        with self.assertRaises(CheckError):
            verify_dependency_archive(path, spec)

    def test_alias_traversal_duplicate_and_foreign_root_fail(self):
        for name in ("Core/a/../escape", "Core/a//b", "Core/./file", "/Core/file", "Other/file", "Core/LICENSE", "Core/a\\b"):
            with self.subTest(name=name):
                path, spec = self.archive([(name, "synthetic")])
                with self.assertRaises(CheckError):
                    verify_dependency_archive(path, spec)

    def test_symlink_member_and_archive_path_fail(self):
        path, spec = self.archive()
        info = zipfile.ZipInfo("Core/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr(info, "LICENSE")
        spec.update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaises(CheckError):
            verify_dependency_archive(path, spec)
        linked = self.root / "linked.zip"
        linked.symlink_to(path)
        with self.assertRaises(CheckError):
            verify_dependency_archive(linked, spec)

    def test_current_lock_and_malformed_fields(self):
        raw = (Path(__file__).resolve().parents[1] / "dependencies.lock.json").read_bytes()
        self.assertEqual(len(dependency_specs({"dependencies.lock.json": raw})), 3)
        for field, value in (("file", "../source.zip"), ("url", "http://example.invalid/source.zip"), ("bytes", True), ("notices", [[]])):
            lock = json.loads(raw)
            lock["archives"][0][field] = value
            with self.subTest(field=field), self.assertRaises(CheckError):
                dependency_specs({"dependencies.lock.json": json.dumps(lock).encode()})

    def test_no_download_requires_existing_verified_cache(self):
        raw = (Path(__file__).resolve().parents[1] / "dependencies.lock.json").read_bytes()
        with self.assertRaises(CheckError):
            cached_dependencies({"dependencies.lock.json": raw}, self.root / "empty", no_download=True)

    def test_build_uses_verified_local_archives_and_refuses_double_override(self):
        framework, framework_spec = self.archive()
        platform = self.root / "platform.zip"
        with zipfile.ZipFile(platform, "w") as archive:
            archive.writestr("Platform/platform.json", json.dumps({"name": "espressif8266", "version": "2026.04.00"}))
            archive.writestr("Platform/LICENSE", "Synthetic platform license")
        platform_spec = dict(framework_spec, id="platform", package="espressif8266", version="2026.04.00",
                             file=platform.name, root="Platform", metadata="platform.json",
                             bytes=platform.stat().st_size, sha256=hashlib.sha256(platform.read_bytes()).hexdigest())
        lwip, lwip_spec = self.stack_archive()
        files = {"dependencies.lock.json": json.dumps({"archives": [platform_spec, framework_spec, lwip_spec]}).encode()}
        source = self.root / "prepared"
        source.mkdir()
        config = source / "platformio_override.ini"
        config.write_text("[env:sonoff4chpro-lease]\nbuild_flags = -DSYNTHETIC_TEST\n")
        paths = {"platform": platform, "framework": framework, "lwip-source": lwip}
        apply_dependency_overrides(source, files, paths)
        self.assertIn("platform = " + platform.as_uri(), config.read_text())
        self.assertIn("framework-arduinoespressif8266 @ " + framework.as_uri(), config.read_text())
        with self.assertRaises(CheckError):
            apply_dependency_overrides(source, files, paths)

    def stack_archive(self):
        path = self.root / "lwip.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Stack/src/include/lwip/init.h", "#define LWIP_VERSION_MAJOR 2\n#define LWIP_VERSION_MINOR 1\n#define LWIP_VERSION_REVISION 2\n")
            archive.writestr("Stack/COPYING", "Synthetic BSD notice")
        return path, {"id": "lwip-source", "package": "lwip", "version": "2.1.2",
                      "file": path.name, "url": "https://download-mirror.savannah.gnu.org/releases/lwip/lwip-2.1.2.zip",
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
                      "root": "Stack", "metadata": "src/include/lwip/init.h", "notices": ["COPYING"]}

    def test_editable_lwip_source_version_and_notice(self):
        path, spec = self.stack_archive()
        verify_dependency_archive(path, spec)
        with self.assertRaises(CheckError):
            verify_dependency_archive(path, dict(spec, version="2.1.3"))

    def test_duplicate_dependency_lock_fields_are_rejected(self):
        raw = (Path(__file__).resolve().parents[1] / "dependencies.lock.json").read_bytes()
        duplicate = b'{"archives":[],' + raw.lstrip()[1:]
        with self.assertRaises(CheckError):
            dependency_specs({"dependencies.lock.json": duplicate})


if __name__ == "__main__":
    unittest.main()
