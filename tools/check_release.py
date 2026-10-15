#!/usr/bin/env python3
"""Review source files, staged index bytes or a source archive without networking."""
import argparse
from pathlib import Path
import sys
import subprocess
sys.dont_write_bytecode = True
from repo_tools import (CheckError, archive_files, external_path, source_digest,
                        staged_files, verify_build_bundle, verify_source_manifest, working_files, write_source_archive)
from repo_tools import verify_generated_source_archive
from release_tools import check_history, require_clean, verify_release_candidate, verify_publication_archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="Inspect actual Git index bytes, including uncommitted staged files")
    mode.add_argument("--archive", type=Path, help="Inspect an existing generated project-source tar.gz, including complete archive metadata")
    mode.add_argument("--build-dir", type=Path, help="Verify final firmware artifacts, hashes, source bundle and current firmware-source match")
    mode.add_argument("--release-dir", type=Path, help="Verify a local versioned candidate against exact clean HEAD")
    parser.add_argument("--history", action="store_true", help="Inspect every Git object, ref and local identity/config metadata without exporting .git")
    parser.add_argument("--require-clean", action="store_true", help="Require committed HEAD with a clean worktree and index")
    parser.add_argument("--approved-authors", type=Path, help="External private JSON array of approved exact name/email pairs")
    parser.add_argument("--release-archive", type=Path, help="With --release-dir, verify the versioned download archive and adjacent .sha256")
    parser.add_argument("--match-working-tree", action="store_true", help="With --build-dir, require the complete bundled project snapshot to equal the working source tree")
    parser.add_argument("--write-archive", type=Path, help="Write checked source bytes to a new archive outside every checkout")
    args = parser.parse_args()
    checked_head = require_clean() if args.require_clean else None
    def verify_unchanged_head():
        if checked_head is not None and require_clean() != checked_head:
            raise CheckError("Git HEAD changed during the release check")
    if args.history:
        counts = check_history(approval_path=args.approved_authors)
        print("Git history/admin checks passed:", counts)
        print("Local Git paths/hooks are administrative data and are never exported; approval values are suppressed.")
    if args.release_dir:
        if args.write_archive or args.match_working_tree:
            parser.error("--release-dir cannot be combined with source-archive/build modifiers")
        verify_release_candidate(args.release_dir, approval_path=args.approved_authors)
        if args.release_archive:
            verify_publication_archive(args.release_archive, args.release_dir)
        verify_unchanged_head()
        print("Local release candidate checks passed against exact clean HEAD; no publication performed.")
        return
    if args.release_archive:
        parser.error("--release-archive requires --release-dir")
    if args.build_dir:
        if args.write_archive:
            parser.error("--write-archive cannot be combined with --build-dir")
        verify_build_bundle(args.build_dir, working_files(), args.match_working_tree)
        verify_unchanged_head()
        print("Build bundle checks passed: exact artifacts, hashes, pinned upstream, paired editable source and reviewed firmware bytes.")
        print("These checks do not establish that compilation occurred or prove device/electrical behavior.")
        return
    if args.match_working_tree:
        parser.error("--match-working-tree requires --build-dir")
    files = archive_files(args.archive) if args.archive else staged_files() if args.staged else working_files()
    if args.archive:
        verify_generated_source_archive(args.archive, files)
    verify_source_manifest(files)
    if args.write_archive:
        output = external_path(args.write_archive)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_source_archive(output, files)
        if archive_files(output) != files:
            raise CheckError("Written archive differs from the checked source bytes")
        verify_generated_source_archive(output, files)
    verify_unchanged_head()
    print(f"Source privacy/integrity checks passed: {len(files)} files, sha256 {source_digest(files)}")
    print("Pattern checks supplement explicit index/archive review; they do not prove absence of private data.")


if __name__ == "__main__":
    try:
        main()
    except (CheckError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
