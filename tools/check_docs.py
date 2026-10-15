"""Offline local Markdown links and current release-metadata checks."""
from __future__ import annotations

import posixpath
import re
import sys
import urllib.parse

sys.dont_write_bytecode = True
from repo_tools import CheckError, strict_json, working_files


def heading_ids(text: str) -> set[str]:
    identifiers = set()
    counts = {}
    text = re.sub(r"(?ms)^```[^\n]*\n.*?^```\s*$", "", text)
    for heading in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", text):
        value = re.sub(r"[^\w\-\s]", "", heading.lower()).replace(" ", "-")
        number = counts.get(value, 0)
        counts[value] = number + 1
        identifiers.add(value if not number else f"{value}-{number}")
    return identifiers


def check_docs(files: dict[str, bytes]) -> int:
    project = strict_json(files["project.json"])
    if not isinstance(project, dict) or set(project) != {"name", "version", "license", "protocolVersion", "buildIdentity"}:
        raise CheckError("Project metadata contains missing or unknown fields")
    if not isinstance(project["version"], str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", project["version"]):
        raise CheckError("Project version must use numeric MAJOR.MINOR.PATCH")
    if project["name"] != "sonoff-4chpro-mqtt" or project["license"] != "GPL-3.0-or-later" or type(project["protocolVersion"]) is not int or project["protocolVersion"] != 1:
        raise CheckError("Project identity/license/protocol metadata is inconsistent")
    if not isinstance(project["buildIdentity"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", project["buildIdentity"]):
        raise CheckError("Unsafe build identity")
    state = strict_json(files["schemas/state.schema.json"])
    if state["properties"]["build"].get("const") != project["buildIdentity"]:
        raise CheckError("State schema build identity differs from project metadata")
    for name in ("README.md", "CHANGELOG.md", "RELEASE_NOTES.md"):
        if project["version"] not in files[name].decode():
            raise CheckError(f"Current release version is missing from {name}")
    documents = {name: data.decode() for name, data in files.items() if name.endswith(".md")}
    for name, text in documents.items():
        visible = re.sub(r"(?ms)^```[^\n]*\n.*?^```\s*$", "", text)
        for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", visible):
            target = target.split(' "', 1)[0].strip().strip("<>")
            url = urllib.parse.urlsplit(target)
            if url.scheme in ("http", "https", "mailto"):
                continue
            if url.scheme or url.netloc or url.path.startswith("/"):
                raise CheckError(f"Unsafe or installation-specific Markdown link in {name}")
            path = urllib.parse.unquote(url.path)
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), path)) if path else name
            if resolved not in files:
                raise CheckError(f"Missing local Markdown target from {name}: {resolved}")
            if url.fragment and resolved in documents and urllib.parse.unquote(url.fragment) not in heading_ids(documents[resolved]):
                raise CheckError(f"Missing local Markdown anchor from {name}: {resolved}")
    return len(documents)


if __name__ == "__main__":
    try:
        print(f"Documentation checks passed: {check_docs(working_files())} Markdown files and current project metadata")
    except (CheckError, KeyError, OSError, ValueError) as error:
        sys.exit(str(error))
