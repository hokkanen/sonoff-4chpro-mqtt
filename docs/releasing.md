# Local release preparation

Version **0.1.0** is the initial candidate. A version edit, passing test or local
commit does not publish a release or qualify connected loads. The protocol remains
`v:1` independently of the project and upstream Tasmota versions.

1. Review source, overlay, patch, schemas, examples, documentation and notices
   together. Record validation with the exact tested image; do not relabel older
   live results as a later deployment. Update [the change log](../CHANGELOG.md).
2. Run `tools/check.py` and a real pinned ESP8285 build using external working and
   output directories. Preserve the firmware, SHA-256 manifest and corresponding
   editable source/overlay/patch/build metadata together.
3. Independently audit actuation, deadlines, parsing and release behavior. Check
   privacy manually across the intended tree, staged index and retained history.
   Keep actual addresses, device identifiers, credentials, backups, live tokens,
   captures and private installation paths outside the repository.
4. Use `tools/check_release.py --staged` for the intended index and its `--archive`
   mode for a prepared distribution. Pattern scanning supplements manual review;
   it cannot establish privacy or electrical correctness by itself.
5. Review the exact source and generated archive contents before an authorized
   commit/publication. Include source, build metadata, licenses and notices with
   distributed firmware; retain the corresponding pinned upstream source.

Local preparation may create reviewed local commits. Publishing, pushing, marking
a release, flashing and connected-load commissioning require authorization for
their actual effects; a passing check or local commit does not authorize them.
Do not publish private commissioning artifacts or pretend hosted CI ran before
an authorized upload. Verify public links and the hosted workflow after publication.

An installed update must preserve the safe inactive board profile. A rollback to
stock Tasmota removes the custom gate and needs a fresh operational safety review.
Keep verified original and pre-change backups privately recoverable; do not ship
them in the source distribution.
