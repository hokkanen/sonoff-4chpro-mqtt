#!/usr/bin/env python3
"""Review source files, staged index bytes or a source archive without networking."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from repo_tools import (CheckError, archive_files, external_path, source_digest,
                        staged_files, verify_build_bundle, verify_source_manifest, working_files, write_source_archive)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="Inspect actual Git index bytes, including uncommitted staged files")
    mode.add_argument("--archive", type=Path, help="Inspect an existing source tar archive")
    mode.add_argument("--build-dir", type=Path, help="Verify final firmware artifacts, hashes, source bundle and current firmware-source match")
    parser.add_argument("--match-working-tree", action="store_true", help="With --build-dir, require the complete bundled project snapshot to equal the working source tree")
    parser.add_argument("--write-archive", type=Path, help="Write checked source bytes to a new archive outside every checkout")
    args = parser.parse_args()
    if args.build_dir:
        if args.write_archive:
            parser.error("--write-archive cannot be combined with --build-dir")
        verify_build_bundle(args.build_dir, working_files(), args.match_working_tree)
        print("Build bundle checks passed: exact artifacts, hashes, pinned upstream, paired editable source and reviewed firmware bytes.")
        print("These checks do not establish that compilation occurred or prove device/electrical behavior.")
        return
    if args.match_working_tree:
        parser.error("--match-working-tree requires --build-dir")
    files = archive_files(args.archive) if args.archive else staged_files() if args.staged else working_files()
    verify_source_manifest(files)
    if args.write_archive:
        output = external_path(args.write_archive)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_source_archive(output, files)
        if archive_files(output) != files:
            raise CheckError("Written archive differs from the checked source bytes")
    print(f"Source privacy/integrity checks passed: {len(files)} files, sha256 {source_digest(files)}")
    print("Pattern checks supplement explicit index/archive review; they do not prove absence of private data.")


if __name__ == "__main__":
    try:
        main()
    except (CheckError, OSError, ValueError) as error:
        sys.exit(str(error))
