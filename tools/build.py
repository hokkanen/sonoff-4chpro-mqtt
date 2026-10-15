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
sys.dont_write_bytecode = True
from repo_tools import (CheckError, external_path, file_sha256, source_digest,
                        verify_build_bundle, verify_source_manifest, working_files, write_source_archive)


def verify_archive(path: Path, lock: dict) -> None:
    if path.stat().st_size != lock["archiveBytes"] or file_sha256(path) != lock["archiveSha256"]:
        raise CheckError("Upstream archive size/SHA-256 mismatch; refusing extraction")


def download(path: Path, lock: dict) -> None:
    url = urllib.parse.urlsplit(lock["archiveUrl"])
    if url.scheme != "https" or url.hostname != "codeload.github.com":
        raise CheckError("Upstream lock must name the official HTTPS codeload host")
    partial = path.with_suffix(".partial")
    try:
        with urllib.request.urlopen(lock["archiveUrl"], timeout=60) as response, partial.open("xb") as output:
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
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def extract_archive(path: Path, destination: Path, commit: str) -> None:
    expected_root = "Tasmota-" + commit
    seen = set()
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != expected_root or ".." in parts or "\\" in member.name or member.name.startswith("/"):
                raise CheckError("Unsafe upstream archive member path")
            if len(seen) >= 60000 or member.name in seen:
                raise CheckError("Duplicate or excessive upstream archive entries")
            seen.add(member.name)
            if not member.isfile() and not member.isdir():
                raise CheckError("Upstream archive links and special files are forbidden")
            total += member.size
            if total > 750 * 1024 * 1024 or member.size > 64 * 1024 * 1024:
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True, help="External parent for fresh prepared source workspaces")
    parser.add_argument("--output-dir", type=Path, help="New/empty external directory for firmware and matching source bundle")
    parser.add_argument("--archive", type=Path, help="Existing upstream archive; size and hash are always checked")
    parser.add_argument("--platformio-core-dir", type=Path, help="External PlatformIO dependency cache; default WORK/platformio-core")
    parser.add_argument("--platformio", default="platformio", help="PlatformIO 6.1.19 executable, not a shell command")
    parser.add_argument("--jobs", type=int, default=4, choices=range(1, 33), metavar="1..32")
    parser.add_argument("--prepare-only", action="store_true", help="Verify/extract/patch only, without invoking PlatformIO")
    parser.add_argument("--no-download", action="store_true", help="Require an existing upstream archive")
    args = parser.parse_args()
    if not args.prepare_only and args.output_dir is None:
        parser.error("--output-dir is required for a firmware build")
    work = external_path(args.work_dir)
    core_dir = external_path(args.platformio_core_dir or work / "platformio-core")
    output = external_path(args.output_dir) if args.output_dir else None
    if output and output.exists() and any(output.iterdir()):
        raise CheckError("Output directory must be new/empty; refusing stale artifact reuse")
    files = working_files()
    verify_source_manifest(files)
    lock = json.loads(files["upstream.lock.json"])
    project = json.loads(files["project.json"])
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
    if args.prepare_only:
        print(json.dumps({"sourceDirectory": str(source), "projectSha256": digest}, indent=2))
        return
    environment = dict(os.environ, PLATFORMIO_CORE_DIR=str(core_dir), PLATFORMIO_SETTING_ENABLE_TELEMETRY="no", PYTHONDONTWRITEBYTECODE="1")
    version = subprocess.run([args.platformio, "--version"], check=True, capture_output=True, text=True, env=environment).stdout.strip()
    if version != "PlatformIO Core, version " + lock["platformioVersion"]:
        raise CheckError("PlatformIO version mismatch; install requirements-build.txt in an external virtual environment")
    subprocess.run([args.platformio, "run", "--environment", lock["environment"], "--jobs", str(args.jobs)], cwd=source, env=environment, check=True)
    binary = source / ".pio/build" / lock["environment"] / "firmware.bin"
    header = binary.read_bytes()[:4]
    if len(header) != 4 or header[0] != 0xe9 or header[2:4] != b"\x03\x20" or binary.stat().st_size > 995326:
        raise CheckError("Built image is not the expected DOUT/40MHz/1MB ESP8285 image")
    output.mkdir(parents=True, exist_ok=True)
    target = output / "sonoff4chpro-lease.bin"
    shutil.copyfile(binary, target)
    import gzip
    with (output / "sonoff4chpro-lease.bin.gz").open("xb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0, filename="") as compressed:
            compressed.write(target.read_bytes())
    source_name = "project-source.tar.gz"
    write_source_archive(output / source_name, files)
    upstream_name = "Tasmota-" + lock["commit"] + ".tar.gz"
    shutil.copyfile(archive, output / upstream_name)
    for name in ("LICENSE", "NOTICE"):
        (output / name).write_bytes(files[name])
    manifest = {"project": project, "projectSha256": digest, "upstream": lock,
                "platformioVersion": lock["platformioVersion"], "flash": {"mode": "dout", "frequencyMHz": 40, "sizeBytes": 1048576},
                "sourceBundle": [source_name, upstream_name], "files": {}}
    for path in sorted(output.iterdir()):
        manifest["files"][path.name] = {"sha256": file_sha256(path), "bytes": path.stat().st_size}
    (output / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verify_build_bundle(output, files, match_tree=True)
    print("Build passed; firmware, verified upstream archive and matching editable project source preserved together.")
    print("Source inputs are pinned. Build timestamps/toolchain environment may change binary bytes.")


if __name__ == "__main__":
    try:
        main()
    except (CheckError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
