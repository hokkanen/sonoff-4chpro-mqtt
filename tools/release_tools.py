"""Offline Git provenance and local publication-candidate helpers. GPL-3.0-or-later."""
from __future__ import annotations

import json
import gzip
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tarfile

from repo_tools import (ROOT, MAX_FILE_BYTES, CheckError, check_content, external_path,
                        file_sha256, safe_name, source_digest, verify_build_bundle,
                        verify_source_manifest, StreamDigest, verify_generated_gzip,
                        strict_json, read_json_file, source_metadata)

NEUTRAL_AUTHORS = {("sonoff-4chpro-mqtt contributors", "contributors@example.invalid")}


def git(*args: str, root: Path = ROOT, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=root, input=data, capture_output=True, check=True).stdout


def approved_authors(path: Path | None) -> set[tuple[str, str]]:
    approved = set(NEUTRAL_AUTHORS)
    if path is None:
        return approved
    path = external_path(path)
    if path.stat().st_size > 65536:
        raise CheckError("Author approval file is oversized")
    value = read_json_file(path)
    if not isinstance(value, list):
        raise CheckError("Author approvals must be an array of exact name/email pairs")
    for item in value:
        if not isinstance(item, dict) or set(item) != {"name", "email"}:
            raise CheckError("Author approval entry has unknown or missing fields")
        if any(not isinstance(item[key], str) or not item[key] or any(ord(c) < 32 for c in item[key]) for key in item):
            raise CheckError("Author approval entry is invalid (values suppressed)")
        approved.add((item["name"], item["email"]))
    return approved


def identity(name: str, email: str, approved: set[tuple[str, str]], scope: str) -> None:
    if (name, email) not in approved:
        raise CheckError(f"Unapproved identity in {scope}; provide an explicit external author approval file (values suppressed)")


def require_clean(root: Path = ROOT) -> str:
    head = git("rev-parse", "--verify", "HEAD", root=root).decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", head):
        raise CheckError("A committed Git HEAD is required")
    if git("status", "--porcelain=v1", "--untracked-files=all", "--ignored", root=root):
        raise CheckError("A clean committed worktree and index are required")
    return head


def head_files(root: Path = ROOT) -> dict[str, bytes]:
    files = {}
    for row in git("ls-tree", "-rz", "--full-tree", "HEAD", root=root).split(b"\0"):
        if not row:
            continue
        meta, raw_path = row.split(b"\t", 1)
        mode, kind, digest = meta.split()
        if mode not in (b"100644", b"100755") or kind != b"blob":
            raise CheckError("HEAD contains a link, submodule or unsupported source entry")
        name = raw_path.decode("utf-8")
        if int(git("cat-file", "-s", digest.decode(), root=root)) > MAX_FILE_BYTES:
            raise CheckError("HEAD contains an oversized source entry")
        data = git("cat-file", "blob", digest.decode(), root=root)
        check_content(name, data)
        files[name] = data
    verify_source_manifest(files)
    return files


def check_unattributed_identity(data: bytes, approved: set[tuple[str, str]]) -> None:
    # Approval applies only to parsed attribution fields. It never exempts the
    # same private identity in a source file, message, path or config value.
    for name, email in approved - NEUTRAL_AUTHORS:
        if name.encode() in data or email.encode() in data:
            raise CheckError("Approved attribution identity appears outside a Git identity field (values suppressed)")


def check_history(root: Path = ROOT, approval_path: Path | None = None) -> dict[str, int]:
    approved = approved_authors(approval_path)
    counts = {"blob": 0, "tree": 0, "commit": 0, "tag": 0, "refs": 0, "config": 0, "reflogIdentities": 0}
    rows = git("cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype) %(objectsize)", root=root)
    for row in rows.splitlines():
        digest, kind, size = row.decode("ascii").split()
        if kind not in ("blob", "tree", "commit", "tag") or int(size) > MAX_FILE_BYTES:
            raise CheckError("Git history contains an unsupported or oversized object")
        counts[kind] += 1
        if kind == "tree":
            for entry in git("ls-tree", "-z", digest, root=root).split(b"\0"):
                if not entry:
                    continue
                meta, raw_name = entry.split(b"\t", 1)
                mode, _kind, _digest = meta.split()
                if mode not in (b"040000", b"100644", b"100755"):
                    raise CheckError("Git history contains a link or submodule")
                name = raw_name.decode("utf-8")
                safe_name(name)
                check_content("git-tree-path", raw_name)
                check_unattributed_identity(raw_name, approved)
            continue
        body = git("cat-file", kind, digest, root=root)
        if kind in ("commit", "tag"):
            header_bytes, separator, message = body.partition(b"\n\n")
            header = header_bytes.decode("utf-8")
            expected = {"author", "committer"} if kind == "commit" else {"tagger"}
            seen = set()
            other_headers = []
            for line in header.splitlines():
                label = line.split(" ", 1)[0]
                if label not in expected:
                    other_headers.append(line)
                    continue
                match = re.fullmatch(r"(?:author|committer|tagger) (.+) <([^<>]+)> [0-9]+ [+-][0-9]{4}", line)
                if not match or label in seen:
                    raise CheckError("Malformed Git identity metadata")
                identity(match[1], match[2], approved, "Git " + kind)
                seen.add(label)
            if seen != expected:
                raise CheckError("Git object is missing required identity metadata")
            body = "\n".join(other_headers).encode() + separator + message
        check_content("git-" + kind + "-object", body)
        check_unattributed_identity(body, approved)
    for raw in git("for-each-ref", "--format=%(refname)", root=root).splitlines():
        check_content("git-ref", raw)
        safe_name(raw.decode("utf-8"))
        check_unattributed_identity(raw, approved)
        counts["refs"] += 1
    # Config is not exported. Standard local filesystem pointers and hook paths
    # are administrative data, not source/history publication findings.
    config = {}
    for row in git("config", "--local", "--null", "--list", root=root).split(b"\0"):
        if not row:
            continue
        key, _, raw_value = row.partition(b"\n")
        name = key.decode("utf-8").lower()
        counts["config"] += 1
        config[name] = raw_value.decode("utf-8")
        if name in ("core.worktree", "core.hookspath"):
            continue
        check_content("git-local-config", key + b"=" + raw_value)
        if name not in ("user.name", "user.email"):
            check_unattributed_identity(key + b"=" + raw_value, approved)
        if name.startswith(("credential.", "http.")) and any(word in name for word in ("extraheader", "password", "token", "secret")):
            raise CheckError("Sensitive local Git configuration requires review (values suppressed; config is not exported)")
    if "user.name" in config or "user.email" in config:
        if not all(key in config for key in ("user.name", "user.email")):
            raise CheckError("Incomplete local Git identity requires review (values suppressed)")
        identity(config["user.name"], config["user.email"], approved, "local Git identity")
    raw_reflogs = git("reflog", "show", "--all", "--format=%gn%x00%ge%x00%gs", root=root)
    for line in raw_reflogs.splitlines():
        fields = line.split(b"\0")
        if len(fields) != 3:
            raise CheckError("Malformed reflog identity metadata")
        identity(fields[0].decode("utf-8"), fields[1].decode("utf-8"), approved, "local reflog")
        check_content("git-reflog-message", fields[2])
        check_unattributed_identity(fields[2], approved)
        counts["reflogIdentities"] += 1
    return counts


def verify_release_candidate(directory: Path, root: Path = ROOT, approval_path: Path | None = None) -> dict:
    directory = external_path(directory)
    head = require_clean(root)
    checked = head_files(root)
    from check_docs import check_docs
    check_docs(checked)
    check_history(root, approval_path)
    manifest_path = directory / "release.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise CheckError("Release metadata must be a regular file")
    release = read_json_file(manifest_path, canonical=True)
    expected_keys = {"project", "version", "sourceCommit", "sourceSha256", "upstreamCommit", "buildManifestSha256", "artifactDirectory", "files"}
    if not isinstance(release, dict) or set(release) != expected_keys:
        raise CheckError("Release metadata has missing or unknown fields")
    project, upstream = source_metadata(checked)
    if release["project"] != project["name"] or release["version"] != project["version"] or release["sourceCommit"] != head or release["sourceSha256"] != source_digest(checked) or release["upstreamCommit"] != upstream["commit"] or release["artifactDirectory"] != "firmware":
        raise CheckError("Release provenance differs from exact clean HEAD")
    build_manifest = verify_build_bundle(directory / "firmware", checked, match_tree=True)
    allowed = {"LICENSE", "NOTICE", "RELEASE_NOTES.md", "SECURITY.md", "release.json", "SHA256SUMS", "firmware/build-manifest.json"}
    allowed.update("firmware/" + name for name in build_manifest["files"])
    found = {}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise CheckError("Release candidate contains a symlink")
        if path.is_file():
            name = path.relative_to(directory).as_posix()
            if name not in allowed:
                raise CheckError("Release candidate contains an unexpected publication path")
            found[name] = file_sha256(path)
        elif path.is_dir():
            if path.relative_to(directory).as_posix() != "firmware":
                raise CheckError("Release candidate contains an unexpected directory")
        else:
            raise CheckError("Release candidate contains a special file")
    payload = {name: digest for name, digest in found.items() if name not in ("SHA256SUMS", "release.json")}
    if release["files"] != payload or set(found) != allowed:
        raise CheckError("Release candidate has missing, changed or unexpected files")
    sums = "".join(f"{digest}  {name}\n" for name, digest in sorted(found.items()) if name != "SHA256SUMS")
    if (directory / "SHA256SUMS").read_text() != sums:
        raise CheckError("Release SHA256SUMS does not match the candidate")
    for name in ("LICENSE", "NOTICE", "RELEASE_NOTES.md", "SECURITY.md"):
        if (directory / name).read_bytes() != checked[name]:
            raise CheckError("Release legal/security/notes content differs from HEAD")
    if release["buildManifestSha256"] != found["firmware/build-manifest.json"]:
        raise CheckError("Release references a different build manifest")
    if require_clean(root) != head:
        raise CheckError("HEAD changed during release verification")
    return release


def verify_publication_archive(archive_path: Path, candidate: Path) -> None:
    """Compare a download asset to the already verified candidate, without extraction."""
    archive_path = external_path(archive_path)
    release = read_json_file(candidate / "release.json", canonical=True)
    expected_name = release["project"] + "-" + release["version"]
    if candidate.name != expected_name or archive_path.name != expected_name + ".tar.gz":
        raise CheckError("Publication directory and download archive must use the current project-version name")
    if archive_path.is_symlink() or not archive_path.is_file():
        raise CheckError("Publication archive must be a regular file")
    checksum = archive_path.with_name(archive_path.name + ".sha256")
    if checksum.is_symlink() or not checksum.is_file() or checksum.read_text() != f"{file_sha256(archive_path)}  {archive_path.name}\n":
        raise CheckError("Publication archive checksum mismatch")
    expected = {candidate.name + "/" + path.relative_to(candidate).as_posix(): path
                for path in candidate.rglob("*") if path.is_file()}
    seen = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            if member.name not in expected or member.name in seen or not member.isfile() or member.issparse():
                raise CheckError("Publication archive contains an unexpected, repeated or non-file member")
            seen.add(member.name)
            if member.uid or member.gid or member.uname or member.gname or member.mtime or member.mode != 0o644 or member.pax_headers:
                raise CheckError("Publication archive has unexpected administrative metadata")
            original = expected[member.name]
            if member.size != original.stat().st_size:
                raise CheckError("Publication archive member size mismatch")
            digest = hashlib.sha256()
            stream = archive.extractfile(member)
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            if digest.hexdigest() != file_sha256(original):
                raise CheckError("Publication archive content differs from the verified candidate")
    if seen != set(expected):
        raise CheckError("Publication archive has missing files")
    canonical = StreamDigest()
    write_publication_tar(candidate, canonical)
    verify_generated_gzip(archive_path, canonical)


def write_publication_tar(candidate: Path, stream) -> None:
    with tarfile.open(fileobj=stream, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
        for path in sorted(candidate.rglob("*")):
            if path.is_file():
                member = tarfile.TarInfo(candidate.name + "/" + path.relative_to(candidate).as_posix())
                member.size = path.stat().st_size
                member.mode = 0o644
                with path.open("rb") as source:
                    archive.addfile(member, source)


def write_publication_archive(candidate: Path) -> Path:
    archive_path = candidate.with_name(candidate.name + ".tar.gz")
    checksum = archive_path.with_name(archive_path.name + ".sha256")
    if archive_path.exists() or archive_path.is_symlink() or checksum.exists() or checksum.is_symlink():
        raise CheckError("Publication asset already exists; refusing overwrite")
    descriptor, filename = tempfile.mkstemp(prefix=".sonoff-asset-", suffix=".partial", dir=candidate.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
                write_publication_tar(candidate, compressed)
        os.link(temporary, archive_path)  # Atomic publication, never replace a concurrent writer.
        with checksum.open("x") as stream:
            stream.write(f"{file_sha256(archive_path)}  {archive_path.name}\n")
    finally:
        temporary.unlink(missing_ok=True)
    verify_publication_archive(archive_path, candidate)
    return archive_path


def prepare_release(build_dir: Path, output_parent: Path, version: str | None,
                    approval_path: Path | None = None, root: Path = ROOT) -> Path:
    head = require_clean(root)
    files = head_files(root)
    from check_docs import check_docs
    check_docs(files)
    check_history(root, approval_path)
    project, upstream = source_metadata(files)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", project["name"]):
        raise CheckError("Unsafe project release name")
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", project["version"]) or (version is not None and version != project["version"]):
        raise CheckError("Release version must exactly match project.json's stable version")
    for name in ("RELEASE_NOTES.md", "SECURITY.md", "LICENSE", "NOTICE"):
        if name not in files:
            raise CheckError("Release notes, security policy and legal notices must be committed before preparation")
    build_dir = external_path(build_dir)
    verify_build_bundle(build_dir, files, match_tree=True)
    output_parent = external_path(output_parent)
    output_parent.mkdir(parents=True, exist_ok=True)
    destination = output_parent / (project["name"] + "-" + project["version"])
    if destination.exists():
        raise CheckError("Release candidate already exists; refusing overwrite")
    staging = Path(tempfile.mkdtemp(prefix=".sonoff-release-", dir=output_parent))
    shutil.copytree(build_dir, staging / "firmware", symlinks=False)
    for name in ("RELEASE_NOTES.md", "SECURITY.md", "LICENSE", "NOTICE"):
        (staging / name).write_bytes(files[name])
    payload = {path.relative_to(staging).as_posix(): file_sha256(path) for path in sorted(staging.rglob("*")) if path.is_file()}
    release = {"project": project["name"], "version": project["version"], "sourceCommit": head,
               "sourceSha256": source_digest(files), "upstreamCommit": upstream["commit"],
               "buildManifestSha256": payload["firmware/build-manifest.json"], "artifactDirectory": "firmware", "files": payload}
    (staging / "release.json").write_text(json.dumps(release, indent=2) + "\n")
    payload["release.json"] = file_sha256(staging / "release.json")
    (staging / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(payload.items())))
    verify_release_candidate(staging, root, approval_path)
    if require_clean(root) != head or destination.exists():
        raise CheckError("Release state changed before publication; candidate remains staged externally")
    staging.rename(destination)
    write_publication_archive(destination)
    verify_release_candidate(destination, root, approval_path)
    verify_publication_archive(destination.with_name(destination.name + ".tar.gz"), destination)
    if require_clean(root) != head:
        raise CheckError("Git HEAD changed before release preparation completed")
    return destination
