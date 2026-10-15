import io
import ast
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from repo_tools import (CheckError, archive_files, check_content, external_path,
                        file_sha256, safe_name, sha256, source_digest,
                        verify_build_bundle, write_source_archive, strict_json)
from build import (PLATFORM_PATCH, build_environment, download, extract_archive,
                   publish_directory, verify_archive, prepare_platform,
                   select_prepared_platform)
from release_tools import (NEUTRAL_AUTHORS, check_history, git, prepare_release,
                           verify_publication_archive, verify_release_candidate)


class SourceBoundaries(unittest.TestCase):
    def test_paths_and_artifacts_fail_closed(self):
        for name in ("../escape", "/escape", "a\\escape", "a//escape", "a/./escape", ".", "private/settings.json", "captures/events.json", "firmware.bin", ".git/config", "settings-backup.json"):
            with self.subTest(name=name), self.assertRaises(CheckError):
                safe_name(name)

    def test_obvious_installation_and_key_filenames_are_not_source(self):
        for name in ("secrets.json", "secret.yaml", "secrets/device.txt", ".env.local", "before-settings.dmp",
                     "device.pem", "device.key", "identity.p12", "identity.pfx", "approved-authors.json"):
            with self.subTest(name=name), self.assertRaises(CheckError):
                check_content(name, b'{"password":"synthetic"}')

    def test_network_identity_in_filename_is_also_rejected(self):
        address = ".".join(("192", "168", "2", "9"))
        with self.assertRaises(CheckError):
            check_content(address + "-notes.md", b"Synthetic note")

    def test_duplicate_json_and_non_finite_numbers_fail_at_source_boundary(self):
        for data in (b'{"a":1,"a":2}', b'{"nested":{"a":1,"a":2}}',
                     b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}', b'{"a":1e999}'):
            with self.subTest(data=data), self.assertRaises(CheckError):
                strict_json(data)
            with self.assertRaises(CheckError):
                check_content("example.json", data)

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

    def test_source_archive_rejects_alias_paths_and_owner_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, (name, owner) in enumerate((("a//b.txt", ""), ("a.txt", "unapproved-owner"))):
                archive = Path(directory) / f"source-{index}.tar.gz"
                with tarfile.open(archive, "w:gz") as stream:
                    info = tarfile.TarInfo(name); info.size = 1; info.uname = owner
                    stream.addfile(info, io.BytesIO(b"x"))
                with self.assertRaises(CheckError):
                    archive_files(archive)

    def test_environment_discards_alternative_build_inputs(self):
        supplied = {"PATH": "synthetic-path", "PLATFORMIO_BUILD_FLAGS": "unreviewed-flags",
                    "PLATFORMIO_PROJECT_DIR": "unreviewed-project", "CXXFLAGS": "unreviewed-flags",
                    "PYTHONPATH": "unreviewed-modules", "PYTHONEXEPATH": "unreviewed-python", "HTTPS_PROXY": "synthetic-proxy"}
        with patch.dict("os.environ", supplied, clear=True):
            clean = build_environment(Path("/external/core"))
        self.assertNotIn("PLATFORMIO_BUILD_FLAGS", clean)
        self.assertNotIn("PLATFORMIO_PROJECT_DIR", clean)
        self.assertNotIn("CXXFLAGS", clean)
        self.assertNotIn("PYTHONPATH", clean)
        self.assertNotIn("PYTHONEXEPATH", clean)
        self.assertEqual(clean["PATH"], "synthetic-path")
        self.assertEqual(clean["PLATFORMIO_CORE_DIR"], "/external/core")

    def test_atomic_output_does_not_overwrite_late_files(self):
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "staging"; staging.mkdir()
            (staging / "firmware.txt").write_text("new")
            output = Path(directory) / "output"; output.mkdir()
            (output / "late.txt").write_text("preserve")
            with self.assertRaises(CheckError):
                publish_directory(staging, output)
            self.assertEqual((output / "late.txt").read_text(), "preserve")
            self.assertTrue(staging.is_dir())


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

    def test_download_does_not_replace_an_existing_writer_or_fixed_partial(self):
        class Response(io.BytesIO):
            def geturl(self):
                return "https://codeload.github.com/example/source"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "upstream.tar.gz"
            data = b"Synthetic verified source"
            path.write_bytes(data)
            sentinel = path.with_suffix(".partial"); sentinel.write_text("another writer")
            lock = {"archiveUrl": "https://codeload.github.com/example/source", "archiveBytes": len(data), "archiveSha256": sha256(data)}
            with patch("build.urllib.request.urlopen", return_value=Response(data)):
                download(path, lock)
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(sentinel.read_text(), "another writer")
            self.assertEqual({p.name for p in path.parent.iterdir()}, {path.name, sentinel.name})

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


class PlatformCompatibility(unittest.TestCase):
    def test_checked_patch_uses_host_environment_without_bootstrap(self):
        import types
        patch_text = (Path(__file__).resolve().parents[1] / PLATFORM_PATCH).read_text()
        self.assertIn('-    "tool-scons",', patch_text)
        self.assertIn('+has_network = False', patch_text)
        # Execute the actual replacement function carried by the reviewed patch.
        lines = []; collecting = False
        for line in patch_text.splitlines(keepends=True):
            if line.startswith(' def _setup_python_environment_core('):
                collecting = True
            elif collecting and line.startswith(' def _setup_pipenv_minimal('):
                break
            if collecting and line[:1] in (' ', '+'):
                lines.append(line[1:])
        module = ast.parse(''.join(lines))
        with tempfile.TemporaryDirectory() as temporary:
            scripts = Path(temporary); (scripts / "esptool").write_text("Synthetic host tool")
            observed = []
            namespace = {"Path": Path, "sys": types.SimpleNamespace(executable="reviewed-host-python"),
                         "IS_WINDOWS": False, "_setup_certifi_env": lambda *args: observed.append(args)}
            exec(compile(module, "actual-platform-compatibility-patch", "exec"), namespace)
            adapter = namespace["_setup_python_environment_core"]
            versions = {"platformio": "6.2.0", "starlette": "1.8.0", "pip": "26.2.1", "esptool": "5.2.0"}
            before = list(sys.path)
            with patch("importlib.metadata.version", side_effect=versions.__getitem__), patch("sysconfig.get_path", return_value=str(scripts)):
                result = adapter(None, object(), "unused")
            self.assertEqual(result, ("reviewed-host-python", str(scripts / "esptool")))
            self.assertEqual(sys.path, before)
            self.assertEqual(observed, [(None, "reviewed-host-python")])
            versions["platformio"] = "unsupported"
            with patch("importlib.metadata.version", side_effect=versions.__getitem__), self.assertRaises(SystemExit):
                adapter(None, object(), "unused")

    def test_prepared_platform_is_fresh_variant_and_selected_directly(self):
        import zipfile
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive = base / "platform.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("platform-1.0.0/platform.json", json.dumps({"name": "espressif8266", "version": "1.0.0"}))
                stream.writestr("platform-1.0.0/LICENSE", "Synthetic license")
                stream.writestr("platform-1.0.0/platform.py", "before\n")
            spec = {"id": "platform", "package": "espressif8266", "version": "1.0.0", "root": "platform-1.0.0",
                    "bytes": archive.stat().st_size, "sha256": file_sha256(archive), "metadata": "platform.json", "notices": ["LICENSE"]}
            patch_path = base / "compat.patch"
            patch_path.write_text("--- a/platform.py\n+++ b/platform.py\n@@ -1 +1 @@\n-before\n+after\n")
            prepared = base / "prepared"
            inventory = prepare_platform(archive, spec, prepared, patch_path)
            metadata = json.loads((prepared / "platform.json").read_text())
            self.assertEqual(metadata["version"], "1.0.0-sonoff.h" + file_sha256(patch_path))
            self.assertIn("2026-10-15", metadata["description"])
            self.assertEqual(inventory["platform.py"], sha256(b"after\n"))
            with self.assertRaises(FileExistsError):
                prepare_platform(archive, spec, prepared, patch_path)
            source = base / "firmware-source"; source.mkdir()
            config = source / "platformio_override.ini"
            config.write_text("[env:synthetic]\nplatform = " + archive.as_uri() + "\n")
            select_prepared_platform(source, archive, prepared)
            self.assertIn("\nplatform = " + prepared.as_posix() + "\n", config.read_text())
            with self.assertRaises(CheckError):
                select_prepared_platform(source, archive, prepared)


class ArtifactBundle(unittest.TestCase):
    def fixture(self, directory):
        import gzip
        import zipfile
        upstream = b"synthetic upstream source"
        lock = {"tag": "v15.6.0", "commit": "f" * 40, "archiveBytes": len(upstream), "archiveSha256": sha256(upstream),
                "platformioVersion": "6.2.0", "environment": "sonoff4chpro-lease",
                "archiveUrl": "https://codeload.github.com/arendst/Tasmota/tar.gz/" + "f" * 40}
        project = {"name": "sonoff-4chpro-mqtt", "version": "0.1.0", "license": "GPL-3.0-or-later",
                   "protocolVersion": 1, "buildIdentity": "sonoff4chpro-lease-v1"}
        files = {"upstream.lock.json": json.dumps(lock).encode(), "project.json": json.dumps(project).encode(),
                 "firmware/source-manifest.json": b'{"sha256":{}}', "LICENSE": b"GPL-3.0-or-later", "NOTICE": b"Synthetic fixture",
                 "README.md": b"Synthetic version 0.1.0", "CHANGELOG.md": b"Synthetic version 0.1.0",
                 "RELEASE_NOTES.md": b"Synthetic version 0.1.0", "SECURITY.md": b"Synthetic security guidance",
                 "schemas/state.schema.json": json.dumps({"properties": {"build": {"const": project["buildIdentity"]}}}).encode()}
        specs = []
        for kind, package, metadata in (("platform", "espressif8266", "platform.json"),
                                        ("framework", "framework-arduinoespressif8266", "package.json"),
                                        ("lwip-source", "lwip", "src/include/lwip/init.h")):
            name = kind + "-source.zip"
            version = "2.1.2" if kind == "lwip-source" else "1.0.0"
            prefix = kind + "-" + version
            notice = "COPYING" if kind == "lwip-source" else "LICENSE"
            package_metadata = ("#define LWIP_VERSION_MAJOR 2\n#define LWIP_VERSION_MINOR 1\n#define LWIP_VERSION_REVISION 2\n"
                                if kind == "lwip-source" else json.dumps({"name": package, "version": version}))
            path = directory / name
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(prefix + "/" + metadata, package_metadata)
                archive.writestr(prefix + "/" + notice, "Synthetic source license")
            specs.append({"id": kind, "package": package, "version": version, "file": name,
                          "url": ("https://download-mirror.savannah.gnu.org/releases/lwip/lwip-2.1.2.zip" if kind == "lwip-source" else
                                  "https://github.com/tasmota/example/releases/download/v1/source.zip"),
                          "sha256": file_sha256(path), "bytes": path.stat().st_size,
                          "root": prefix, "metadata": metadata, "notices": [notice]})
        files["dependencies.lock.json"] = json.dumps({"archives": specs}).encode()
        upstream_name = "Tasmota-" + lock["commit"] + ".tar.gz"
        binary = b"\xe9\x01\x03\x20synthetic-not-real-firmware"
        (directory / "sonoff4chpro-lease.bin").write_bytes(binary)
        compressed = io.BytesIO()
        with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0) as stream:
            stream.write(binary)
        (directory / "sonoff4chpro-lease.bin.gz").write_bytes(compressed.getvalue())
        (directory / upstream_name).write_bytes(upstream)
        write_source_archive(directory / "project-source.tar.gz", files)
        for name in ("LICENSE", "NOTICE"):
            (directory / name).write_bytes(files[name])
        manifest = {"project": project, "upstream": lock, "projectSha256": source_digest(files),
                    "platformioVersion": "6.2.0", "sourceBundle": ["project-source.tar.gz", upstream_name, *[s["file"] for s in specs]],
                    "flash": {"mode": "dout", "frequencyMHz": 40, "sizeBytes": 1048576},
                    "files": {p.name: {"sha256": file_sha256(p), "bytes": p.stat().st_size} for p in directory.iterdir()}}
        (directory / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
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
            (directory / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            with self.assertRaises(CheckError):
                verify_build_bundle(directory, files)

    def test_bundle_unknown_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            files, manifest = self.fixture(directory)
            manifest["unexpectedMetadata"] = "unreviewed"
            (directory / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            with self.assertRaises(CheckError):
                verify_build_bundle(directory, files)

    def test_duplicate_or_noncanonical_generated_metadata_rejected(self):
        for mutation in ("duplicate", "noncanonical", "wrong-type"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                files, manifest = self.fixture(directory)
                path = directory / "build-manifest.json"
                if mutation == "duplicate":
                    path.write_text('{"project":"SYNTHETIC-PRIVATE-METADATA",' + path.read_text().lstrip()[1:])
                elif mutation == "noncanonical":
                    path.write_text(json.dumps(manifest))
                else:
                    manifest["project"]["protocolVersion"] = True
                    path.write_text(json.dumps(manifest, indent=2) + "\n")
                with self.assertRaises(CheckError):
                    verify_build_bundle(directory, files)

    def test_source_archive_cannot_hide_gzip_metadata_or_trailing_bytes(self):
        for mutation in ("trailing", "gzip-name"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                files, manifest = self.fixture(directory)
                archive = directory / "project-source.tar.gz"
                raw = archive.read_bytes()
                if mutation == "trailing":
                    changed = raw + b"Synthetic extra data after the archive"
                else:
                    changed = raw[:3] + b"\x08" + raw[4:10] + b"synthetic-name\0" + raw[10:]
                archive.write_bytes(changed)
                manifest["files"][archive.name] = {"sha256": file_sha256(archive), "bytes": archive.stat().st_size}
                (directory / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
                with self.assertRaises(CheckError):
                    verify_build_bundle(directory, files)

    def test_firmware_gzip_cannot_hide_metadata_or_additional_members(self):
        import gzip
        for mutation in ("name", "comment", "empty-member", "trailing"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                files, manifest = self.fixture(directory)
                archive = directory / "sonoff4chpro-lease.bin.gz"
                raw = archive.read_bytes()
                if mutation in ("name", "comment"):
                    flag = b"\x08" if mutation == "name" else b"\x10"
                    changed = raw[:3] + flag + raw[4:10] + b"SYNTHETIC-PRIVATE-METADATA\0" + raw[10:]
                elif mutation == "empty-member":
                    changed = raw + gzip.compress(b"", mtime=0)
                else:
                    changed = raw + b"Synthetic trailing bytes"
                archive.write_bytes(changed)
                manifest["files"][archive.name] = {"sha256": file_sha256(archive), "bytes": archive.stat().st_size}
                (directory / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
                with self.assertRaises(CheckError):
                    verify_build_bundle(directory, files)


class ReleaseBoundaries(unittest.TestCase):
    def fixture(self, parent):
        build = parent / "build"; build.mkdir()
        files, _manifest = ArtifactBundle().fixture(build)
        repo = parent / "repository"; repo.mkdir()
        for name, data in files.items():
            path = repo / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        git("init", "--initial-branch=main", root=repo)
        name, email = next(iter(NEUTRAL_AUTHORS))
        git("config", "user.name", name, root=repo)
        git("config", "user.email", email, root=repo)
        git("add", "--all", root=repo)
        git("commit", "-m", "Synthetic release fixture", root=repo)
        return repo, build

    def test_clean_head_candidate_and_reproducible_download_asset(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo, build = self.fixture(parent)
            candidate = prepare_release(build, parent / "publication", None, root=repo)
            verify_release_candidate(candidate, root=repo)
            archive = candidate.with_name(candidate.name + ".tar.gz")
            verify_publication_archive(archive, candidate)
            second = prepare_release(build, parent / "second-publication", "0.1.0", root=repo)
            self.assertEqual(archive.read_bytes(), second.with_name(second.name + ".tar.gz").read_bytes())
            with self.assertRaises(CheckError):
                prepare_release(build, parent / "publication", "0.1.0", root=repo)
            with self.assertRaises(CheckError):
                prepare_release(build, parent / "third-publication", "0.2.0", root=repo)

    def test_extra_path_cannot_be_blessed_by_updated_release_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo, build = self.fixture(parent)
            candidate = prepare_release(build, parent / "publication", None, root=repo)
            extra = candidate / "extra" / "unreviewed.txt"; extra.parent.mkdir(); extra.write_text("Synthetic extra data")
            manifest = candidate / "release.json"; value = json.loads(manifest.read_text())
            value["files"]["extra/unreviewed.txt"] = file_sha256(extra)
            manifest.write_text(json.dumps(value, indent=2) + "\n")
            sums = {p.relative_to(candidate).as_posix(): file_sha256(p) for p in candidate.rglob("*") if p.is_file() and p.name != "SHA256SUMS"}
            (candidate / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(sums.items())))
            with self.assertRaises(CheckError):
                verify_release_candidate(candidate, root=repo)
            extra.unlink()
            with self.assertRaises(CheckError):
                verify_release_candidate(candidate, root=repo)  # Unexpected empty directory still fails.

    def test_history_includes_unreachable_objects_and_identity_approval_is_narrow(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo, _build = self.fixture(parent)
            self.assertGreater(check_history(repo)["blob"], 0)
            person = "Synthetic" + " Person"
            email = "synthetic" + "@example.invalid"
            approvals = parent / "author-policy.json"
            approvals.write_text(json.dumps([{"name": person, "email": email}]))
            git("config", "user.name", person, root=repo)
            git("config", "user.email", email, root=repo)
            git("commit", "--allow-empty", "-m", "Approved attribution fixture", root=repo)
            with self.assertRaises(CheckError):
                check_history(repo)
            check_history(repo, approvals)
            # An unreachable blob still crosses the eventual publication boundary.
            git("hash-object", "-w", "--stdin", root=repo, data=("Personal note for " + person).encode())
            with self.assertRaises(CheckError):
                check_history(repo, approvals)

    def test_dirty_source_and_mutated_download_checksum_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo, build = self.fixture(parent)
            candidate = prepare_release(build, parent / "publication", None, root=repo)
            archive = candidate.with_name(candidate.name + ".tar.gz")
            archive.with_name(archive.name + ".sha256").write_text("unreviewed checksum")
            with self.assertRaises(CheckError):
                verify_publication_archive(archive, candidate)
            (repo / "README.md").write_text("Dirty source")
            with self.assertRaises(CheckError):
                prepare_release(build, parent / "second", None, root=repo)

    def test_download_cannot_hide_bytes_even_with_updated_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo, build = self.fixture(parent)
            candidate = prepare_release(build, parent / "publication", None, root=repo)
            archive = candidate.with_name(candidate.name + ".tar.gz")
            archive.write_bytes(archive.read_bytes() + b"Synthetic extra data after archive")
            archive.with_name(archive.name + ".sha256").write_text(f"{file_sha256(archive)}  {archive.name}\n")
            with self.assertRaises(CheckError):
                verify_publication_archive(archive, candidate)

    def test_candidate_is_rechecked_after_archive_creation(self):
        import release_tools
        original = release_tools.write_publication_archive
        def alter_after_archive(candidate):
            result = original(candidate)
            (candidate / "SECURITY.md").write_text("Synthetic concurrent modification")
            return result
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo, build = self.fixture(parent)
            with patch("release_tools.write_publication_archive", side_effect=alter_after_archive), self.assertRaises(CheckError):
                prepare_release(build, parent / "publication", None, root=repo)

    def test_duplicate_release_metadata_and_private_archive_root_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo, build = self.fixture(parent)
            candidate = prepare_release(build, parent / "publication", None, root=repo)
            metadata = candidate / "release.json"
            original = metadata.read_text()
            metadata.write_text('{"project":"SYNTHETIC-PRIVATE-METADATA",' + original.lstrip()[1:])
            with self.assertRaises(CheckError):
                verify_release_candidate(candidate, root=repo)
            metadata.write_text(original)
            renamed = candidate.with_name("unreviewed-directory-name"); candidate.rename(renamed)
            with self.assertRaises(CheckError):
                verify_publication_archive(candidate.with_name(candidate.name + ".tar.gz"), renamed)
