# Security boundaries

This firmware controls physical relay outputs. Protocol validation and a local
expiry timer reduce accidental stale control; they do not establish electrical
safety or protect against every firmware, power or hardware failure.

## Trusted network and publishers

The Lite profile uses unencrypted MQTT and HTTP. It does not provide MQTT TLS or
an authenticated cryptographic device identity. Keep the device and broker on a
trusted, isolated local network; do not expose either interface to the Internet.
Set a unique administrator password during commissioning. Do not compile or
commit installation credentials, and do not put them in URLs or shell history.

Use separate broker accounts and narrow topic permissions. An ordinary controller
needs to publish only `cmnd/sonoff4chpro/LEASE` and read the custom reply and
availability topics. Keep native maintenance commands restricted to administrators.
The device itself needs its command subscriptions and state/availability writes.
Enforce a non-retaining control-publisher policy and clean sessions. Consult the
[retain limitation](docs/protocol.md#transport-and-evidence) before choosing broker
controls; topic permissions alone do not necessarily filter the retain flag.

The `owner` string is coordination data, not authenticated application authority.
MAC binding prevents accidental device substitution, not spoofing by an attacker.
Nonces and lease tokens travel through the broker; a reader of the reply topic or
an observer of the unencrypted network can see temporary capabilities. The lease
gate does not defend against a malicious broker, compromised administrator,
authorized hostile publisher, network denial of service or physical access.
An administrator can replace firmware or change configuration. The host must
independently enforce master/standby ownership at the actual publication boundary.

This build has one fixed MQTT topic profile. Deploy one such board per
broker namespace; do not install multiple identical profiles on the same broker.
A fleet profile with separately reviewed identities/topics is outside this release.

## Actuation limits

Only a current accepted lease authorizes GPIO activation. Lost replies are unknown,
and a deadline passing at the host is not fresh OFF evidence. Native maintenance
queries terminate an active lease. Silent network failure is bounded by the local
deadline after transport detection delays; it does not imply immediate OFF.

GPIO feedback does not sense mechanical contacts, welded relays, RF hardware,
connected equipment or an electrically safe fallback. Software begins controlling
pins only after it starts. Brownouts, boot-ROM behavior and hardware damage remain
outside its guarantees. Read [commissioning requirements](docs/operations.md) and
the precise [validation limits](docs/status.md) before connecting any load.

## Reporting

Do not include credentials, device identifiers, network details, settings/flash
backups, live tokens or household logs in issues or pull requests. Use synthetic
reproductions. Report vulnerabilities through GitHub private vulnerability
reporting when it is enabled on the published repository. If that channel is
unavailable, post only a request for a private contact without exploit details.
This local release candidate has no configured hosted reporting channel yet.

The current candidate is the only reviewed project version. Review upstream
Tasmota and dependency advisories as well as this repository before an update;
a passing offline test suite is not a guarantee that all vulnerabilities are known.
