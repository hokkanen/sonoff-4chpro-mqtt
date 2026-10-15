#!/usr/bin/env python3
"""Run local host, schema, source-integrity and build-tool checks; no networking."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
sys.dont_write_bytecode = True
from repo_tools import ROOT, CheckError, external_path, verify_source_manifest, working_files, strict_json, source_metadata
from check_docs import check_docs


def schemas(files: dict[str, bytes]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as error:
        raise CheckError("Install requirements-check.txt in an external virtual environment before running checks") from error
    validators = {}
    for name in ("request", "state"):
        schema = strict_json(files[f"schemas/{name}.schema.json"])
        def local_refs(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "$ref" and not value.startswith("#"):
                        raise CheckError("Schema checks must not resolve remote references")
                    local_refs(value)
            elif isinstance(node, list):
                for value in node:
                    local_refs(value)
        local_refs(schema)
        Draft7Validator.check_schema(schema)
        validators[name] = Draft7Validator(schema)
    examples = [name for name in files if name.startswith("examples/") and name.endswith(".json")]
    for name in examples:
        value = strict_json(files[name])
        validator = validators["state" if "kind" in value else "request"]
        errors = list(validator.iter_errors(value))
        if errors:
            raise CheckError(f"Schema example failed validation: {name} ({errors[0].validator})")
        # JSON Schema regex '$' can match before a final linefeed. Names may not.
        for field in ("id", "owner"):
            if field in value and value[field]:
                for suffix in ("\n", "\r\n"):
                    malformed = dict(value, **{field: value[field] + suffix})
                    if validator.is_valid(malformed):
                        raise CheckError(f"Schema accepts a forbidden trailing control character: {name}/{field}")
    print(f"Schema checks passed: 2 local-only schemas, {len(examples)} examples")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanitizers", action="store_true", help="Compile C++ host tests with AddressSanitizer and UndefinedBehaviorSanitizer")
    parser.add_argument("--compiler", default="g++", help="C++11 compiler executable")
    parser.add_argument("--work-dir", type=Path, default=Path("/var/tmp"), help="External parent for temporary test binaries; default /var/tmp")
    args = parser.parse_args()
    files = working_files()
    verify_source_manifest(files)
    source_metadata(files)
    print(f"Documentation checks passed: {check_docs(files)} Markdown files and current metadata")
    schemas(files)
    base = external_path(args.work_dir)
    base.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(base))
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"], cwd=ROOT, env=environment, check=True)
    with tempfile.TemporaryDirectory(prefix="sonoff-host-check-", dir=base) as folder:
        for header in ("Ticker.h", "osapi.h"):
            (Path(folder) / header).write_text("// Host harness supplies the SDK declarations; no device implementation.\n")
        for name in ("test_lease_core.cpp", "test_lease_json.cpp", "driver-parser-test.cpp", "test_lease_driver.cpp"):
            output = Path(folder) / Path(name).stem
            flags = ["-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "firmware/overlay/tasmota/include"), "-I", folder]
            flags += ["-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if args.sanitizers else ["-O2"]
            subprocess.run([args.compiler, *flags, str(ROOT / "tests" / name), "-o", str(output)], check=True)
            subprocess.run([str(output)], check=True)
    print("Offline checks passed. An ESP8285 build and authorized live commissioning are separate checks.")


if __name__ == "__main__":
    try:
        main()
    except (CheckError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
