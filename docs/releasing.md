# Local release preparation

Version **0.1.0** is the initial candidate. Project version, protocol `v:1` and
upstream Tasmota version are separate identifiers. Local preparation does not
publish a release, authorize flashing or qualify connected loads.

## Review and checks

Review the firmware overlay/patch, parser/core/driver, schemas, examples,
operating/security documents, dependency locks and notices together. Keep earlier
live evidence tied to its tested image. Update [release notes](../RELEASE_NOTES.md),
[the change log](../CHANGELOG.md) and [validation status](status.md).

Run `tools/check.py --sanitizers` and a real ESP8285 build with external work,
dependency-cache and output directories. Preserve the exact project, Tasmota,
platform, framework and lwIP source archives, their notices, firmware and manifest.
Read [dependency provenance](dependencies.md) for the source and toolchain limits.

Use independent reviewers for firmware safety paths and public source/history/
artifact privacy. No scanner can prove absence of private data by itself. Check
all stored Git objects, including unreachable objects, as well as the intended
index and final distribution. A clean worktree alone is insufficient.

## Public attribution

Git author/committer names and emails are public when history is pushed. Keep only
explicitly approved attribution. The default neutral identity uses
`contributors@example.invalid`; an externally stored JSON allowlist can approve
exact existing name/email pairs. It has the shape:

```json
[{"name":"Project contributors","email":"contributors@example.invalid"}]
```

Keep a real approval file outside every Git repository. Pass its location through
`--approved-authors`; never add actual names/emails to public test fixtures or
source exemptions. Approval applies to Git identity fields, not arbitrary personal
content elsewhere. Do not rewrite attribution without the author's informed
approval; a permitted identity does not grant permission to publish secrets.

## Prepare the exact committed candidate

Set the variables below to suitable external paths first. The approval file is
optional when all attribution uses the neutral default. Commit only explicitly
reviewed files before preparing a publication candidate.

```sh
python3 tools/check.py --sanitizers
python3 tools/check_release.py --staged
python3 tools/check_release.py --history --require-clean --approved-authors "$SONOFF_APPROVED_AUTHORS"
python3 tools/check_release.py --build-dir "$SONOFF_BUILD_DIR" --match-working-tree
python3 tools/check_release.py --archive "$SONOFF_BUILD_DIR/project-source.tar.gz"
python3 tools/prepare_release.py --build-dir "$SONOFF_BUILD_DIR" --output-dir "$SONOFF_RELEASE_PARENT" --approved-authors "$SONOFF_APPROVED_AUTHORS"
python3 tools/check_release.py --release-dir "$SONOFF_RELEASE_PARENT/sonoff-4chpro-mqtt-0.1.0" --release-archive "$SONOFF_RELEASE_PARENT/sonoff-4chpro-mqtt-0.1.0.tar.gz" --approved-authors "$SONOFF_APPROVED_AUTHORS"
```

The prepare command creates a versioned local candidate and checksums without
creating a Git tag, remote, upload or GitHub release. Use the command's `--help`
for its exact archive/output layout and final `--release-dir` verification. Keep
binary and matching editable source/notices available together. Do not upload
private commissioning backups, logs, live capabilities or approval files.

Review the exact final index, retained history, release metadata, archive members
and checksums before publication. Confirm that generated files contain no operator
paths, installation settings or device identifiers. Checksums identify bytes; they
are not a maintainer signature or evidence of electrical safety.

## Publication and recovery boundaries

Local preparation may create reviewed local commits. Publishing, pushing, marking
a release, flashing and connected-load commissioning require authorization for
their actual effects. A passing local check is not proof that hosted CI ran.
After an authorized publication, verify the public artifact downloads, workflow,
source availability and vulnerability-reporting channel on GitHub.

An update must preserve inactive startup and the fixed board profile. A rollback
to stock Tasmota removes the custom gate. Retain verified original/pre-change
backups privately; never ship installation firmware/settings dumps with a release.
Recommission affected behavior before using changed actuation code with real loads.
