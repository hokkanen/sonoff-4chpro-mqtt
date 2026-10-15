#!/usr/bin/env python3
"""Prepare a local versioned publication candidate from exact clean HEAD; never uploads or tags."""
import argparse
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
from repo_tools import CheckError
from release_tools import prepare_release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True, help="Verified external build bundle matching clean HEAD")
    parser.add_argument("--output-dir", type=Path, required=True, help="External parent for a new project-version candidate")
    parser.add_argument("--version", help="Optional assertion; must match project.json exactly")
    parser.add_argument("--approved-authors", type=Path, help="External private JSON array of explicitly approved exact name/email pairs")
    args = parser.parse_args()
    destination = prepare_release(args.build_dir, args.output_dir, args.version, args.approved_authors)
    print("Local release candidate prepared and verified; no Git tags, remotes or uploads changed.")
    print("Candidate directory:", destination)
    print("Publication archive:", destination.with_name(destination.name + ".tar.gz"))
    print("Archive checksum:", destination.with_name(destination.name + ".tar.gz.sha256"))
    print("Binary publication still requires reviewed dependency/licensing completeness and authorization.")


if __name__ == "__main__":
    try:
        main()
    except (CheckError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
