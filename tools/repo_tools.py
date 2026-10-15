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
import tarfile

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 10 * 1024 * 1024


class CheckError(ValueError):
    pass


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
    forbidden = {".git", ".pio", ".cache", "node_modules", "__pycache__", ".venv",
                 "private", "backups", "captures", "build_output", "dist"}
    if any(part.lower() in forbidden for part in path.parts):
        raise CheckError(f"Forbidden source path: {name}")
    lowered = path.name.lower()
    if lowered == ".env" or any(word in lowered for word in ("credentials", "wifi_cred", "settings-backup", "flash-backup", "live-events")):
        raise CheckError(f"Installation data filename forbidden: {name}")
    if lowered.endswith((".bin", ".bin.gz", ".elf", ".map", ".pyc", ".log", ".sqlite", ".db", ".tar", ".tar.gz", ".zip")):
        raise CheckError(f"Generated or private artifact forbidden: {name}")


def check_content(name: str, data: bytes) -> None:
    safe_name(name)
    if len(data) > MAX_FILE_BYTES or b"\0" in data:
        raise CheckError(f"Binary/oversized source file: {name}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CheckError(f"Non-text source file: {name}") from error
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
            data = path.read_bytes()
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
    with tarfile.open(path, "r:*") as archive:
        for member in archive:
            safe_name(member.name)
            if member.isdir():
                continue
            if not member.isfile() or member.size > MAX_FILE_BYTES or member.name in files:
                raise CheckError("Source archive contains links, special files, duplicates or oversized entries")
            total += member.size
            if total > MAX_SOURCE_BYTES:
                raise CheckError("Source archive exceeds the reviewed size bound")
            data = archive.extractfile(member).read()
            check_content(member.name, data)
            files[member.name] = data
    return files


def source_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode("utf-8") + b"\0" + data + b"\0")
    return digest.hexdigest()


def write_source_archive(path: Path, files: dict[str, bytes]) -> None:
    import gzip
    with path.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for name, data in sorted(files.items()):
                    check_content(name, data)
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    entry.mode = 0o644
                    entry.mtime = 0
                    archive.addfile(entry, io.BytesIO(data))


def verify_source_manifest(files: dict[str, bytes]) -> None:
    manifest = json.loads(files["firmware/source-manifest.json"])["sha256"]
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
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or set(manifest) != {"project", "projectSha256", "upstream", "platformioVersion", "flash", "sourceBundle", "files"}:
        raise CheckError("Build manifest has missing or unknown metadata fields")
    lock = json.loads(reviewed["upstream.lock.json"])
    project = json.loads(reviewed["project.json"])
    upstream_name = "Tasmota-" + lock["commit"] + ".tar.gz"
    expected = {"sonoff4chpro-lease.bin", "sonoff4chpro-lease.bin.gz", "project-source.tar.gz", upstream_name, "LICENSE", "NOTICE"}
    if set(manifest["files"]) != expected or {p.name for p in directory.iterdir()} != expected | {"build-manifest.json"}:
        raise CheckError("Build bundle has missing, stale or unexpected artifacts")
    for name in expected:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise CheckError("Build bundle contains a link or non-file artifact")
        actual = {"sha256": file_sha256(path), "bytes": path.stat().st_size}
        if manifest["files"][name] != actual:
            raise CheckError(f"Build artifact integrity mismatch: {name}")
    if manifest["upstream"] != lock or manifest["project"] != project or manifest["platformioVersion"] != lock["platformioVersion"]:
        raise CheckError("Build metadata differs from reviewed source/dependency pins")
    if manifest["flash"] != {"mode": "dout", "frequencyMHz": 40, "sizeBytes": 1048576}:
        raise CheckError("Unexpected build flash settings")
    if manifest["sourceBundle"] != ["project-source.tar.gz", upstream_name]:
        raise CheckError("Build is missing its exact corresponding source bundle")
    upstream = directory / upstream_name
    if upstream.stat().st_size != lock["archiveBytes"] or file_sha256(upstream) != lock["archiveSha256"]:
        raise CheckError("Bundled upstream archive differs from the pinned source")
    bundled = archive_files(directory / "project-source.tar.gz")
    verify_source_manifest(bundled)
    if source_digest(bundled) != manifest["projectSha256"]:
        raise CheckError("Project source archive does not match the artifact manifest")
    if json.loads(bundled["upstream.lock.json"]) != lock or json.loads(bundled["project.json"]) != project:
        raise CheckError("Bundled source metadata differs from reviewed metadata")
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
    import gzip
    with gzip.open(directory / "sonoff4chpro-lease.bin.gz", "rb") as stream:
        if stream.read(len(binary) + 1) != binary:
            raise CheckError("Compressed firmware does not match the raw image")
    return manifest
