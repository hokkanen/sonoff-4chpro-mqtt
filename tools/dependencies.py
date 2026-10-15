"""Pinned build and corresponding sources; never installation data or devices."""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import urllib.parse
import urllib.request
import zipfile

from repo_tools import CheckError, external_path, file_sha256, strict_json


def dependency_specs(files: dict[str, bytes]) -> list[dict]:
    lock = strict_json(files["dependencies.lock.json"])
    if not isinstance(lock, dict) or set(lock) != {"archives"} or not isinstance(lock["archives"], list):
        raise CheckError("Invalid dependency source lock")
    specs = lock["archives"]
    expected = {"platform": ("espressif8266", "platform.json"),
                "framework": ("framework-arduinoespressif8266", "package.json"),
                "lwip-source": ("lwip", "src/include/lwip/init.h")}
    if len(specs) != 3 or {s.get("id") for s in specs if isinstance(s, dict)} != set(expected):
        raise CheckError("The dependency lock must contain platform, framework and lwIP source")
    filenames = set()
    for s in specs:
        if set(s) != {"id", "package", "version", "file", "url", "sha256", "bytes", "root", "metadata", "notices"}:
            raise CheckError("Unknown or missing dependency lock fields")
        if (s["package"], s["metadata"]) != expected[s["id"]]:
            raise CheckError("Unexpected dependency package identity")
        if not all(isinstance(s[k], str) for k in ("version", "file", "url", "sha256", "root")):
            raise CheckError("Invalid dependency field types")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*\.zip", s["file"]) or s["file"] in filenames:
            raise CheckError("Unsafe or duplicate dependency archive name")
        filenames.add(s["file"])
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", s["root"]):
            raise CheckError("Unsafe dependency archive root")
        if not re.fullmatch(r"[0-9a-f]{64}", s["sha256"]) or type(s["bytes"]) is not int or not 0 < s["bytes"] <= 64 * 1024 * 1024:
            raise CheckError("Invalid dependency digest or size")
        url = urllib.parse.urlsplit(s["url"])
        official = (url.netloc == "github.com" and url.path.startswith("/tasmota/") and "/releases/download/" in url.path)
        if s["id"] == "lwip-source":
            official = url.netloc == "download-mirror.savannah.gnu.org" and url.path == "/releases/lwip/lwip-" + s["version"] + ".zip"
        if url.scheme != "https" or not official or url.query or url.fragment:
            raise CheckError("Dependency source must use an official HTTPS release asset")
        if not isinstance(s["notices"], list) or not s["notices"] or not all(isinstance(n, str) for n in s["notices"]):
            raise CheckError("Missing or duplicate dependency notices")
        if len(set(s["notices"])) != len(s["notices"]):
            raise CheckError("Duplicate dependency notices")
        for name in s["notices"]:
            if not isinstance(name, str) or PurePosixPath(name).as_posix() != name or name.startswith("/") or ".." in PurePosixPath(name).parts or "\\" in name:
                raise CheckError("Unsafe dependency notice path")
    return specs


def verify_dependency_archive(path: Path, spec: dict) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != spec["bytes"] or file_sha256(path) != spec["sha256"]:
        raise CheckError("Dependency archive size/SHA-256 mismatch")
    prefix = spec["root"] + "/"
    seen = set()
    total = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename
            canonical = name[:-1] if info.is_dir() else name
            parts = PurePosixPath(canonical)
            mode = info.external_attr >> 16
            if (not name.startswith(prefix) or parts.as_posix() != canonical or
                    ".." in parts.parts or "\\" in name or any(ord(c) < 32 or ord(c) == 127 for c in name) or
                    stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)) or
                    name in seen or info.flag_bits & 1):
                raise CheckError("Unsafe dependency archive member")
            seen.add(name)
            total += info.file_size
            if len(seen) > 30000 or info.file_size > 64 * 1024 * 1024 or total > 256 * 1024 * 1024:
                raise CheckError("Dependency source archive exceeds size bounds")
        try:
            if archive.testzip() is not None:
                raise CheckError("Dependency source archive CRC mismatch")
            metadata = archive.read(prefix + spec["metadata"]).decode("utf-8")
            if spec["id"] == "lwip-source":
                parts = [re.search(r"(?m)^#define\s+LWIP_VERSION_" + key + r"\s+(\d+)\s*$", metadata) for key in ("MAJOR", "MINOR", "REVISION")]
                if not all(parts) or ".".join(p.group(1) for p in parts) != spec["version"]:
                    raise CheckError("lwIP source version does not match its lock")
            else:
                package = strict_json(metadata)
                if package.get("name") != spec["package"] or package.get("version") != spec["version"]:
                    raise CheckError("Dependency package metadata does not match its lock")
            for notice in spec["notices"]:
                if not archive.read(prefix + notice).strip():
                    raise CheckError("Empty dependency license notice")
        except KeyError as error:
            raise CheckError("Dependency source or required notice is missing") from error


def cached_dependencies(files: dict[str, bytes], cache: Path, no_download: bool = False) -> dict[str, Path]:
    cache = external_path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    result = {}
    for spec in dependency_specs(files):
        path = cache / spec["file"]
        if not path.exists() and not path.is_symlink():
            if no_download:
                raise CheckError("Pinned dependency archive is missing from the external cache")
            descriptor, filename = tempfile.mkstemp(prefix=".dependency-", suffix=".partial", dir=cache)
            temporary = Path(filename)
            try:
                with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(spec["url"], timeout=30) as response:
                    final = urllib.parse.urlsplit(response.geturl())
                    hosts = ("github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "download-mirror.savannah.gnu.org")
                    if final.scheme != "https" or final.hostname not in hosts:
                        raise CheckError("Unexpected dependency download redirect")
                    total = 0
                    while block := response.read(1024 * 1024):
                        total += len(block)
                        if total > spec["bytes"]:
                            raise CheckError("Dependency download exceeds the pinned size")
                        output.write(block)
                verify_dependency_archive(temporary, spec)
                try:
                    os.link(temporary, path)  # Never overwrite another concurrent cache writer.
                except FileExistsError:
                    verify_dependency_archive(path, spec)
            finally:
                temporary.unlink(missing_ok=True)
        verify_dependency_archive(path, spec)
        result[spec["id"]] = path
    return result


def apply_dependency_overrides(source: Path, files: dict[str, bytes], archives: dict[str, Path]) -> None:
    """Select exact platform/framework inputs and verify paired editable stack source."""
    for spec in dependency_specs(files):
        verify_dependency_archive(archives[spec["id"]], spec)
    config = source / "platformio_override.ini"
    text = config.read_text()
    if "[env:sonoff4chpro-lease]" not in text or re.search(r"(?m)^platform\s*=|^platform_packages\s*=", text):
        raise CheckError("Unexpected platform overrides in the prepared source")
    text += ("\nplatform = " + archives["platform"].as_uri() + "\nplatform_packages =\n"
             "    framework-arduinoespressif8266 @ " + archives["framework"].as_uri() + "\n")
    config.write_text(text)
