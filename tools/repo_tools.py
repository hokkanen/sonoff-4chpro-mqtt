"""Offline source boundaries and integrity helpers. GPL-3.0-or-later."""
from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import stat
import tarfile

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 10 * 1024 * 1024


class CheckError(ValueError):
    pass


def strict_json(data: bytes | str):
    """Decode one JSON value without duplicate keys or non-finite numbers."""
    def object_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise CheckError("JSON contains a duplicate key (input values suppressed)")
            value[key] = item
        return value
    def invalid_number(_value):
        raise CheckError("JSON contains a non-finite number")
    try:
        return json.loads(data, object_pairs_hook=object_pairs, parse_constant=invalid_number,
                          parse_float=lambda number: finite_float(number))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise CheckError("Invalid or excessively nested JSON (input values suppressed)") from error


def finite_float(number: str) -> float:
    import math
    value = float(number)
    if not math.isfinite(value):
        raise CheckError("JSON contains a non-finite number")
    return value


def read_json_file(path: Path, canonical: bool = False):
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_FILE_BYTES:
        raise CheckError("JSON metadata must be a bounded regular file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise CheckError("JSON metadata exceeds the reviewed size bound")
    value = strict_json(raw)
    if canonical and raw != (json.dumps(value, indent=2) + "\n").encode():
        raise CheckError("Generated JSON metadata is not in its canonical public encoding")
    return value


def source_metadata(files: dict[str, bytes]) -> tuple[dict, dict]:
    project = strict_json(files["project.json"])
    fields = {"name", "version", "license", "protocolVersion", "buildIdentity"}
    if (not isinstance(project, dict) or set(project) != fields or
            project["name"] != "sonoff-4chpro-mqtt" or project["license"] != "GPL-3.0-or-later" or
            type(project["protocolVersion"]) is not int or project["protocolVersion"] != 1 or
            not isinstance(project["version"], str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", project["version"]) or
            not isinstance(project["buildIdentity"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", project["buildIdentity"])):
        raise CheckError("Project metadata contains unknown fields or invalid current values")
    lock = strict_json(files["upstream.lock.json"])
    fields = {"tag", "commit", "archiveUrl", "archiveSha256", "archiveBytes", "platformioVersion", "environment"}
    if (not isinstance(lock, dict) or set(lock) != fields or
            not all(isinstance(lock[key], str) for key in fields - {"archiveBytes"}) or
            not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", lock["tag"]) or
            not re.fullmatch(r"[0-9a-f]{40}", lock["commit"]) or
            not re.fullmatch(r"[0-9a-f]{64}", lock["archiveSha256"]) or
            type(lock["archiveBytes"]) is not int or not 0 < lock["archiveBytes"] <= 128 * 1024 * 1024 or
            not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", lock["platformioVersion"]) or
            lock["environment"] != "sonoff4chpro-lease" or
            lock["archiveUrl"] != "https://codeload.github.com/arendst/Tasmota/tar.gz/" + lock["commit"]):
        raise CheckError("Upstream metadata contains unknown fields or invalid current values")
    return project, lock


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def external_path(value: str | Path, root: Path = ROOT) -> Path:
    path = Path(value).expanduser().resolve()
    if path == root.resolve() or root.resolve() in path.parents:
        raise CheckError("Build, cache and output paths must be outside the checkout")
    for ancestor in (path, *path.parents):
        if (ancestor / ".git").exists() or ((ancestor / "HEAD").is_file() and (ancestor / "objects").is_dir()):
            raise CheckError("Build, cache and output paths must be outside all Git repositories")
    return path


def safe_name(name: str) -> None:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise CheckError("Unsafe source archive path")
    if path.as_posix() != name or name == ".":
        raise CheckError("Source paths must use their canonical relative spelling")
    forbidden = {".git", ".pio", ".cache", "node_modules", "__pycache__", ".venv",
                 "private", "secrets", "backups", "captures", "build_output", "dist"}
    if any(part.lower() in forbidden for part in path.parts):
        raise CheckError(f"Forbidden source path: {name}")
    lowered = path.name.lower()
    if (lowered == ".env" or lowered.startswith((".env.", "secret.", "secrets.", "approved-authors.")) or
            any(word in lowered for word in ("credentials", "wifi_cred", "settings-backup", "flash-backup", "live-events"))):
        raise CheckError(f"Installation data filename forbidden: {name}")
    if lowered.endswith((".bin", ".bin.gz", ".elf", ".map", ".pyc", ".log", ".sqlite", ".db", ".dmp", ".pem", ".key", ".p12", ".pfx", ".tar", ".tar.gz", ".zip")):
        raise CheckError(f"Generated or private artifact forbidden: {name}")


def check_content(name: str, data: bytes) -> None:
    safe_name(name)
    if len(data) > MAX_FILE_BYTES or b"\0" in data:
        raise CheckError(f"Binary/oversized source file: {name}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CheckError(f"Non-text source file: {name}") from error
    check_text_privacy("source path", name)
    check_text_privacy(name, text)
    if name.lower().endswith(".json"):
        strict_json(data)


def check_text_privacy(name: str, text: str) -> None:
    patterns = (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"/(?:home|Users)/[A-Za-z0-9_.-]+/",
        r"/var/lib/(?:st-mq|sonoff)[A-Za-z0-9_./-]*",
        r"(?i)(?:mqtt|https?)://[^/\s:@]+:[^/\s@]+@",
    )
    if any(re.search(pattern, text) for pattern in patterns):
        raise CheckError(f"Potential private data in {name}; review locally (values suppressed)")
    for match in re.finditer(r"(?<![\w.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\w.])", text):
        if re.search(r"\bsection\s*$", text[max(0, match.start() - 24):match.start()], re.IGNORECASE):
            continue  # Standards section numbers can have four components.
        try:
            address = ipaddress.IPv4Address(match.group())
        except ipaddress.AddressValueError:
            continue
        documentation = any(address in ipaddress.ip_network(net) for net in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))
        if not (documentation or address.is_loopback or address.is_unspecified):
            raise CheckError(f"Non-documentation network address in {name} (value suppressed)")
    for match in re.finditer(r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f:])", text):
        mac = match.group().upper()
        if not (mac.startswith("AA:BB:CC:") or mac.startswith("02:00:00:") or mac == "00:11:22:33:44:55"):
            raise CheckError(f"Non-synthetic hardware identifier in {name} (value suppressed)")


def working_files(root: Path = ROOT) -> dict[str, bytes]:
    files = {}
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(part for part in dirs if part != ".git")
        for entry in [*(Path(folder) / part for part in dirs), *(Path(folder) / part for part in names)]:
            if entry.is_symlink():
                raise CheckError("Source checkout must not contain symlinks")
        for name in sorted(names):
            if name == ".git":
                continue  # Worktree metadata, never release content.
            path = Path(folder) / name
            relative = path.relative_to(root).as_posix()
            metadata = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_FILE_BYTES:
                raise CheckError("Source tree contains a special or oversized file")
            with path.open("rb") as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            check_content(relative, data)
            files[relative] = data
    if sum(map(len, files.values())) > MAX_SOURCE_BYTES:
        raise CheckError("Source tree exceeds the reviewed size bound")
    return files


def staged_files(root: Path = ROOT) -> dict[str, bytes]:
    entries = subprocess.run(["git", "ls-files", "--stage", "-z"], cwd=root, check=True, capture_output=True).stdout
    files = {}
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, _digest, stage = metadata.split()
        if mode not in (b"100644", b"100755") or stage != b"0":
            raise CheckError("Index contains a link, submodule or unresolved entry")
        name = raw_path.decode("utf-8")
        data = subprocess.run(["git", "show", ":" + name], cwd=root, check=True, capture_output=True).stdout
        check_content(name, data)
        files[name] = data
    if not files:
        raise CheckError("The index is empty; stage reviewed files explicitly first")
    if sum(map(len, files.values())) > MAX_SOURCE_BYTES:
        raise CheckError("Staged source exceeds the reviewed size bound")
    return files


def archive_files(path: Path) -> dict[str, bytes]:
    files = {}
    total = 0
    seen = set()
    with tarfile.open(path, "r:*") as archive:
        for member in archive:
            safe_name(member.name)
            if len(seen) >= 20000 or member.name in seen:
                raise CheckError("Source archive has duplicate or excessive entries")
            seen.add(member.name)
            if member.uname not in ("", "root") or member.gname not in ("", "root"):
                raise CheckError("Source archive contains unreviewed owner metadata")
            for key, value in member.pax_headers.items():
                if key == "path" and value == member.name:
                    continue
                if key == "comment" and re.fullmatch(r"[0-9a-f]{40}", value):
                    continue  # git archive's public commit identifier.
                if key == "mtime" and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
                    continue
                raise CheckError("Source archive contains unreviewed extended metadata")
            if member.isdir():
                continue
            if not member.isfile() or member.size < 0 or member.size > MAX_FILE_BYTES:
                raise CheckError("Source archive contains links, special files, duplicates or oversized entries")
            total += member.size
            if total > MAX_SOURCE_BYTES:
                raise CheckError("Source archive exceeds the reviewed size bound")
            data = archive.extractfile(member).read()
            check_content(member.name, data)
            files[member.name] = data
    if not files:
        raise CheckError("Source archive is empty")
    for name in files:
        if any(parent.as_posix() in files for parent in PurePosixPath(name).parents):
            raise CheckError("Source archive has conflicting file/directory paths")
    return files


def source_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode("utf-8") + b"\0" + data + b"\0")
    return digest.hexdigest()


class StreamDigest:
    """A write-only sink for checking deterministic stream bytes without a copy."""
    def __init__(self):
        self.digest = hashlib.sha256()
        self.size = 0

    def write(self, block):
        self.digest.update(block)
        self.size += len(block)
        return len(block)


def write_source_tar(stream, files: dict[str, bytes]) -> None:
    with tarfile.open(fileobj=stream, mode="w|", format=tarfile.PAX_FORMAT) as archive:
        for name, data in sorted(files.items()):
            check_content(name, data)
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            entry.mode = 0o644
            entry.mtime = 0
            archive.addfile(entry, io.BytesIO(data))


def verify_generated_gzip(path: Path, expected: StreamDigest) -> None:
    """Check the entire generated stream, including metadata and trailing bytes."""
    import struct
    import zlib
    digest = hashlib.sha256()
    crc = 0
    size = 0
    decoder = zlib.decompressobj(-zlib.MAX_WBITS)
    try:
        with path.open("rb") as stream:
            if stream.read(10) != bytes.fromhex("1f8b08000000000002ff"):
                raise CheckError("Generated archive has unexpected gzip header metadata")
            while not decoder.eof:
                block = stream.read(1024 * 1024)
                if not block:
                    raise CheckError("Generated archive is truncated")
                output = decoder.decompress(block, expected.size - size + 1)
                size += len(output)
                if size > expected.size:
                    raise CheckError("Generated archive has unexpected decompressed or trailing content")
                digest.update(output)
                crc = zlib.crc32(output, crc)
            trailer = decoder.unused_data + stream.read(9)
            if len(trailer) != 8 or trailer != struct.pack("<II", crc & 0xffffffff, size & 0xffffffff):
                raise CheckError("Generated archive has an invalid trailer or appended content")
    except zlib.error as error:
        raise CheckError("Generated archive compression is invalid") from error
    if size != expected.size or digest.digest() != expected.digest.digest():
        raise CheckError("Generated archive uncompressed bytes differ from their canonical checked files")


def verify_generated_source_archive(path: Path, files: dict[str, bytes]) -> None:
    expected = StreamDigest()
    write_source_tar(expected, files)
    verify_generated_gzip(path, expected)


def write_source_archive(path: Path, files: dict[str, bytes]) -> None:
    import gzip
    with path.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            write_source_tar(compressed, files)


def verify_source_manifest(files: dict[str, bytes]) -> None:
    document = strict_json(files["firmware/source-manifest.json"])
    if not isinstance(document, dict) or set(document) != {"sha256"} or not isinstance(document["sha256"], dict):
        raise CheckError("Firmware source manifest has unknown or missing fields")
    manifest = document["sha256"]
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in manifest.values()):
        raise CheckError("Firmware source manifest has an invalid SHA-256 value")
    actual = {name for name in files if name.startswith("firmware/") and name != "firmware/source-manifest.json"}
    if actual != set(manifest):
        raise CheckError("Firmware source manifest has missing or unexpected paths")
    for name, expected in manifest.items():
        if sha256(files[name]) != expected:
            raise CheckError(f"Firmware source changed without reviewed manifest update: {name}")


def verify_build_bundle(directory: Path, reviewed: dict[str, bytes], match_tree: bool = False) -> dict:
    """Check paired artifacts/source bytes, not whether a compiler ran or hardware works."""
    directory = external_path(directory)
    manifest_path = directory / "build-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise CheckError("Build manifest must be a regular file")
    manifest = read_json_file(manifest_path, canonical=True)
    if not isinstance(manifest, dict) or set(manifest) != {"project", "projectSha256", "upstream", "platformioVersion", "flash", "sourceBundle", "files"}:
        raise CheckError("Build manifest has missing or unknown metadata fields")
    project, lock = source_metadata(reviewed)
    from dependencies import dependency_specs, verify_dependency_archive
    dependencies = dependency_specs(reviewed)
    dependency_names = [spec["file"] for spec in dependencies]
    upstream_name = "Tasmota-" + lock["commit"] + ".tar.gz"
    expected = {"sonoff4chpro-lease.bin", "sonoff4chpro-lease.bin.gz", "project-source.tar.gz", upstream_name, "LICENSE", "NOTICE", *dependency_names}
    if not isinstance(manifest["files"], dict) or set(manifest["files"]) != expected or {p.name for p in directory.iterdir()} != expected | {"build-manifest.json"}:
        raise CheckError("Build bundle has missing, stale or unexpected artifacts")
    for name in expected:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise CheckError("Build bundle contains a link or non-file artifact")
        actual = {"sha256": file_sha256(path), "bytes": path.stat().st_size}
        record = manifest["files"][name]
        if (not isinstance(record, dict) or set(record) != {"sha256", "bytes"} or
                not isinstance(record["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) or
                type(record["bytes"]) is not int):
            raise CheckError("Build artifact metadata has unknown fields or invalid types")
        if manifest["files"][name] != actual:
            raise CheckError(f"Build artifact integrity mismatch: {name}")
    manifest_project, manifest_upstream = source_metadata({"project.json": json.dumps(manifest["project"]).encode(),
                                                           "upstream.lock.json": json.dumps(manifest["upstream"]).encode()})
    if manifest_upstream != lock or manifest_project != project or manifest["platformioVersion"] != lock["platformioVersion"]:
        raise CheckError("Build metadata differs from reviewed source/dependency pins")
    if (manifest["flash"] != {"mode": "dout", "frequencyMHz": 40, "sizeBytes": 1048576} or
            type(manifest["flash"]["frequencyMHz"]) is not int or type(manifest["flash"]["sizeBytes"]) is not int):
        raise CheckError("Unexpected build flash settings")
    if manifest["sourceBundle"] != ["project-source.tar.gz", upstream_name, *dependency_names]:
        raise CheckError("Build is missing its exact corresponding source bundle")
    upstream = directory / upstream_name
    if upstream.stat().st_size != lock["archiveBytes"] or file_sha256(upstream) != lock["archiveSha256"]:
        raise CheckError("Bundled upstream archive differs from the pinned source")
    bundled = archive_files(directory / "project-source.tar.gz")
    verify_generated_source_archive(directory / "project-source.tar.gz", bundled)
    verify_source_manifest(bundled)
    if source_digest(bundled) != manifest["projectSha256"]:
        raise CheckError("Project source archive does not match the artifact manifest")
    if source_metadata(bundled) != (project, lock):
        raise CheckError("Bundled source metadata differs from reviewed metadata")
    if bundled["dependencies.lock.json"] != reviewed["dependencies.lock.json"]:
        raise CheckError("Bundled dependency sources differ from the reviewed lock")
    for spec in dependencies:
        verify_dependency_archive(directory / spec["file"], spec)
    reviewed_firmware = {name: data for name, data in reviewed.items() if name.startswith("firmware/")}
    bundled_firmware = {name: data for name, data in bundled.items() if name.startswith("firmware/")}
    if reviewed_firmware != bundled_firmware:
        raise CheckError("Bundled firmware source differs from the current reviewed firmware")
    if match_tree and bundled != reviewed:
        raise CheckError("Bundled project snapshot differs from the current reviewed source tree")
    for name in ("LICENSE", "NOTICE"):
        if (directory / name).read_bytes() != bundled[name]:
            raise CheckError("Build legal notices differ from bundled corresponding source")
    binary = (directory / "sonoff4chpro-lease.bin").read_bytes()
    if len(binary) < 4 or len(binary) > 995326 or binary[0] != 0xe9 or binary[2:4] != b"\x03\x20":
        raise CheckError("Unexpected ESP8285 binary header or size")
    expected_binary = StreamDigest()
    expected_binary.write(binary)
    verify_generated_gzip(directory / "sonoff4chpro-lease.bin.gz", expected_binary)
    return manifest
