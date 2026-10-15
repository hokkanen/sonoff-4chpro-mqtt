#!/usr/bin/env python3
"""Build the pinned Sonoff firmware in a fresh workspace outside all checkouts.

Downloads only the integrity-pinned upstream archive and PlatformIO build inputs.
Never reads installation settings, connects to devices, installs or flashes firmware.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
sys.dont_write_bytecode = True
from repo_tools import (CheckError, external_path, file_sha256, source_digest,
                        verify_build_bundle, verify_source_manifest, working_files, write_source_archive, source_metadata, strict_json)
from dependencies import apply_dependency_overrides, cached_dependencies, dependency_specs, verify_dependency_archive

PLATFORM_PATCH = "tools/patches/platform-espressif8266-2026.04.00.patch"


def platform_inventory(source: Path) -> dict[str, str]:
    files = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise CheckError("Prepared platform contains a link or special file")
        if path.is_file():
            files[path.relative_to(source).as_posix()] = file_sha256(path)
    return files


def prepare_platform(archive: Path, spec: dict, destination: Path, patch_path: Path) -> dict[str, str]:
    """Derive the reviewed build-only recipe without changing the official ZIP."""
    verify_dependency_archive(archive, spec)
    destination.mkdir()  # Fresh source only; never reuse an operator-modified tree.
    prefix = spec["root"] + "/"
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            relative = member.filename[len(prefix):]
            if not relative:
                continue
            target = destination / relative
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output, source.open(member) as stream:
                    shutil.copyfileobj(stream, output)
                target.chmod(0o755 if (member.external_attr >> 16) & 0o111 else 0o644)
    subprocess.run(["patch", "--batch", "--fuzz=0", "--forward", "-p1", "--input", str(patch_path)],
                   cwd=destination, check=True)
    metadata_path = destination / "platform.json"
    metadata = strict_json(metadata_path.read_bytes())
    base = ".".join(str(int(part)) for part in spec["version"].split("."))
    metadata["version"] = base + "-sonoff.h" + file_sha256(patch_path)
    metadata["description"] = metadata.get("description", "") + " Build recipe modified 2026-10-15 by sonoff-4chpro-mqtt: reviewed host Python and Core-owned SCons."
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return platform_inventory(destination)


def select_prepared_platform(source: Path, original_archive: Path, prepared_platform: Path) -> None:
    config = source / "platformio_override.ini"
    text = config.read_text()
    original = "\nplatform = " + original_archive.as_uri() + "\n"
    if text.count(original) != 1:
        raise CheckError("Unexpected platform source selection in the prepared build")
    # Core's PlatformFactory explicitly loads a directory path directly. This
    # cannot select a previously installed, unpatched platform by name/version.
    config.write_text(text.replace(original, "\nplatform = " + prepared_platform.as_posix() + "\n"))


def verify_archive(path: Path, lock: dict) -> None:
    if path.stat().st_size != lock["archiveBytes"] or file_sha256(path) != lock["archiveSha256"]:
        raise CheckError("Upstream archive size/SHA-256 mismatch; refusing extraction")


def download(path: Path, lock: dict) -> None:
    url = urllib.parse.urlsplit(lock["archiveUrl"])
    if url.scheme != "https" or url.hostname != "codeload.github.com":
        raise CheckError("Upstream lock must name the official HTTPS codeload host")
    descriptor, filename = tempfile.mkstemp(prefix=".upstream-", suffix=".partial", dir=path.parent)
    partial = Path(filename)
    try:
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(lock["archiveUrl"], timeout=60) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname != "codeload.github.com":
                raise CheckError("Unexpected upstream download redirect")
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > lock["archiveBytes"]:
                    raise CheckError("Upstream download exceeds the locked size")
                output.write(block)
        verify_archive(partial, lock)
        try:
            os.link(partial, path)  # Never replace another concurrent cache writer.
        except FileExistsError:
            verify_archive(path, lock)
    finally:
        partial.unlink(missing_ok=True)


def extract_archive(path: Path, destination: Path, commit: str) -> None:
    expected_root = "Tasmota-" + commit
    seen = set()
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != expected_root or ".." in parts or "\\" in member.name or member.name.startswith("/") or PurePosixPath(member.name).as_posix() != member.name:
                raise CheckError("Unsafe upstream archive member path")
            if len(seen) >= 60000 or member.name in seen:
                raise CheckError("Duplicate or excessive upstream archive entries")
            seen.add(member.name)
            if not member.isfile() and not member.isdir():
                raise CheckError("Upstream archive links and special files are forbidden")
            total += member.size
            if total > 750 * 1024 * 1024 or member.size < 0 or member.size > 64 * 1024 * 1024:
                raise CheckError("Upstream extraction size bound exceeded")
            if len(parts) == 1:
                if not member.isdir():
                    raise CheckError("Upstream archive root is not a directory")
                continue
            target = destination.joinpath(*parts[1:])
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output:
                    shutil.copyfileobj(archive.extractfile(member), output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def prepare(source: Path, snapshot: Path, archive: Path, lock: dict) -> None:
    source.mkdir()
    extract_archive(archive, source, lock["commit"])
    subprocess.run(["patch", "--batch", "--fuzz=0", "--forward", "-p1", "--input",
                    str(snapshot / "firmware/patches/tasmota-v15.6.0.patch")], cwd=source, check=True)
    overlay = snapshot / "firmware/overlay"
    for path in sorted(overlay.rglob("*")):
        if path.is_file():
            target = source / path.relative_to(overlay)
            if target.exists():
                raise CheckError("Overlay unexpectedly replaces an upstream file")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def build_environment(core_dir: Path) -> dict[str, str]:
    # These are unrecorded alternative build inputs, not installation settings.
    # Preserve ordinary process/network environment, but never inherit compiler
    # flags, Python module injection, or PlatformIO project/config overrides.
    excluded = {"CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "LIBRARY_PATH",
                "COMPILER_PATH", "GCC_EXEC_PREFIX", "CPPFLAGS", "CFLAGS",
                "CXXFLAGS", "LDFLAGS", "PYTHONPATH", "PYTHONHOME", "PYTHONEXEPATH"}
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("PLATFORMIO_") and key not in excluded}
    environment.update(PLATFORMIO_CORE_DIR=str(core_dir),
                       PLATFORMIO_SETTING_ENABLE_TELEMETRY="no",
                       PYTHONDONTWRITEBYTECODE="1")
    return environment


def publish_directory(assembled: Path, output: Path) -> None:
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise CheckError("Output changed during build; verified candidate left in its external staging directory")
    # Rename will also fail atomically if the destination acquires files after
    # the check; individual output files are never overwritten.
    assembled.rename(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True, help="External parent for fresh prepared source workspaces")
    parser.add_argument("--output-dir", type=Path, help="New/empty external directory for firmware and matching source bundle")
    parser.add_argument("--archive", type=Path, help="Existing upstream archive; size and hash are always checked")
    parser.add_argument("--platformio-core-dir", type=Path, help="External PlatformIO dependency cache; default WORK/platformio-core")
    parser.add_argument("--dependency-cache", type=Path, help="External verified platform/framework archive cache; default WORK/dependency-archives")
    parser.add_argument("--platformio", default="platformio", help="PlatformIO 6.2.0 executable, not a shell command")
    parser.add_argument("--jobs", type=int, default=4, choices=range(1, 33), metavar="1..32")
    parser.add_argument("--prepare-only", action="store_true", help="Verify/extract/patch only, without invoking PlatformIO")
    parser.add_argument("--no-download", action="store_true", help="Require cached upstream/platform/framework archives; PlatformIO still needs its external host-tool cache")
    args = parser.parse_args()
    if not args.prepare_only and args.output_dir is None:
        parser.error("--output-dir is required for a firmware build")
    work = external_path(args.work_dir)
    core_dir = external_path(args.platformio_core_dir or work / "platformio-core")
    dependency_cache = external_path(args.dependency_cache or work / "dependency-archives")
    output = external_path(args.output_dir) if args.output_dir else None
    if output and output.exists() and any(output.iterdir()):
        raise CheckError("Output directory must be new/empty; refusing stale artifact reuse")
    files = working_files()
    verify_source_manifest(files)
    project, lock = source_metadata(files)
    digest = source_digest(files)
    work.mkdir(parents=True, exist_ok=True)
    archive = args.archive.resolve() if args.archive else work / ("Tasmota-" + lock["commit"] + ".tar.gz")
    if not archive.exists():
        if args.archive or args.no_download:
            raise CheckError("Upstream source archive is missing")
        download(archive, lock)
    verify_archive(archive, lock)
    workspace = Path(tempfile.mkdtemp(prefix="sonoff-" + digest[:12] + "-", dir=work))
    snapshot = workspace / "project"
    for name, data in files.items():
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    source = workspace / "firmware-source"
    prepare(source, snapshot, archive, lock)
    archives = cached_dependencies(files, dependency_cache, no_download=args.no_download)
    apply_dependency_overrides(source, files, archives)
    platform_spec = next(spec for spec in dependency_specs(files) if spec["id"] == "platform")
    platform_source = workspace / "platform-source"
    expected_platform = prepare_platform(archives["platform"], platform_spec, platform_source, snapshot / PLATFORM_PATCH)
    select_prepared_platform(source, archives["platform"], platform_source)
    if args.prepare_only:
        print(json.dumps({"sourceDirectory": str(source), "projectSha256": digest}, indent=2))
        return
    environment = build_environment(core_dir)
    version = subprocess.run([args.platformio, "--version"], check=True, capture_output=True, text=True, env=environment).stdout.strip()
    if version != "PlatformIO Core, version " + lock["platformioVersion"]:
        raise CheckError("PlatformIO version mismatch; install requirements-build.txt in an external virtual environment")
    if platform_inventory(platform_source) != expected_platform:
        raise CheckError("Prepared platform changed before compilation")
    subprocess.run([args.platformio, "run", "--environment", lock["environment"], "--jobs", str(args.jobs)], cwd=source, env=environment, check=True)
    binary = source / ".pio/build" / lock["environment"] / "firmware.bin"
    header = binary.read_bytes()[:4]
    if len(header) != 4 or header[0] != 0xe9 or header[2:4] != b"\x03\x20" or binary.stat().st_size > 995326:
        raise CheckError("Built image is not the expected DOUT/40MHz/1MB ESP8285 image")
    # Assemble privately, then publish the whole verified directory atomically.
    # No late file introduced into the requested output can be overwritten.
    output.parent.mkdir(parents=True, exist_ok=True)
    assembled = Path(tempfile.mkdtemp(prefix=".sonoff-artifacts-", dir=output.parent))
    target = assembled / "sonoff4chpro-lease.bin"
    shutil.copyfile(binary, target)
    import gzip
    with (assembled / "sonoff4chpro-lease.bin.gz").open("xb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0, filename="") as compressed:
            compressed.write(target.read_bytes())
    source_name = "project-source.tar.gz"
    write_source_archive(assembled / source_name, files)
    upstream_name = "Tasmota-" + lock["commit"] + ".tar.gz"
    shutil.copyfile(archive, assembled / upstream_name)
    dependency_names = []
    for spec in dependency_specs(files):
        shutil.copyfile(archives[spec["id"]], assembled / spec["file"])
        dependency_names.append(spec["file"])
    for name in ("LICENSE", "NOTICE"):
        (assembled / name).write_bytes(files[name])
    manifest = {"project": project, "projectSha256": digest, "upstream": lock,
                "platformioVersion": lock["platformioVersion"], "flash": {"mode": "dout", "frequencyMHz": 40, "sizeBytes": 1048576},
                "sourceBundle": [source_name, upstream_name, *dependency_names], "files": {}}
    for path in sorted(assembled.iterdir()):
        manifest["files"][path.name] = {"sha256": file_sha256(path), "bytes": path.stat().st_size}
    (assembled / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verify_build_bundle(assembled, files, match_tree=True)
    publish_directory(assembled, output)
    print("Build passed; firmware, verified upstream archive and matching editable project source preserved together.")
    print("Source inputs are pinned. Build timestamps/toolchain environment may change binary bytes.")


if __name__ == "__main__":
    try:
        main()
    except (CheckError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
