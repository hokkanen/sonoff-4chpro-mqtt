# Dependency provenance and distribution

The project modifies pinned Tasmota 15.6.0 source, not an installed firmware dump.
`upstream.lock.json` records its exact commit, archive size and SHA-256. The focused
patch and overlay remain editable in this repository.

`dependencies.lock.json` additionally pins these official archives by size and
SHA-256. Platform and framework are the actual build inputs, not substitutes
assembled from an operator's local cache. lwIP supplies paired editable source:

| Component | Selected version | Source and notices |
| --- | --- | --- |
| Tasmota ESP8266 PlatformIO platform | 2026.04.00 | Official platform release ZIP; build scripts and Apache-2.0 notice. |
| Tasmota ESP8266 Arduino framework | 2.7.8 | Official Arduino release ZIP; core, libraries, bootloader, SDK package and original component notices. |
| lwIP editable stack source | 2.1.2 | Official Savannah release ZIP and COPYING, paired with the framework's lwIP glue/options/patches. |

The original platform ZIP stays unchanged in the release. The build extracts a
fresh copy and applies the checked
[build-only compatibility patch](../tools/patches/platform-espressif8266-2026.04.00.patch)
with zero fuzz. Dated Apache change notices are retained in both modified Python
files and the derived platform description. Its version identifies the patch
SHA-256. PlatformIO loads that exact directory directly rather than selecting a
previously cached unpatched platform with the same upstream version; its inventory
is checked before compilation.

The framework preserves LGPL-2.1 Arduino code, eboot BSD-3-Clause, BearSSL MIT and
the original libb64, umm_malloc, LittleFS, SdFat and SDK notices. Its upstream SDK
contains binary libraries with Espressif's ESP8266-specific license; this project
does not claim that proprietary SDK source has become available. Tasmota's bundled
libraries retain their own source and notices in the Tasmota archive. NOTICE also
records the project's dated upstream modifications.

The framework uses prebuilt lwIP and SDK/C/math libraries. The additional lwIP
source ZIP matches the authoritative `STABLE-2_1_2_RELEASE` source commit
`159e31b689577dbf69cf0683bbaffbd71fa5ee10`; its `src` files match after normalizing
line endings. Existing framework glue/options and all 14 Arduino-target patches
are preserved. Rebuilding that library is separate from the normal firmware
build; normalize the release ZIP's CRLF files before applying the upstream recipe,
which may use ordinary patch context fuzz. This audit does not claim those
libraries were rebuilt or that every prebuilt SDK/C/math component is supplied
as editable source; those components retain their separate upstream terms.

Every binary distribution must include all five corresponding archives: project,
Tasmota, platform, framework and lwIP source, plus LICENSE, NOTICE and the manifest.
Keep recipients' access to matching source equivalent to their access to binary
downloads, as described by [GPLv3 sections 1 and 6](https://www.gnu.org/licenses/gpl-3.0.html).
Do not replace matching archives with a link to a moving source branch.

## Build tools and reproducibility

Python 3.11+ dependencies are version-constrained separately from the firmware
protocol. PlatformIO 6.2.0 permits the patched Starlette 1.8.0 host dependency;
the earlier PlatformIO pin restricted Starlette to an affected series. The build
uses PlatformIO's CLI, not its HTTP server, and this host dependency is not part
of the firmware. Review current advisories rather than reusing an old environment.
The selected platform identifies the Xtensa 4.8.2 compiler package, esptool 5.2.0
and esp_install 5.3.4. The compatibility patch stops its older SCons package
cleanup and nested Python bootstrap; Core 6.2 owns its SCons engine. Required
littlefs, FAT, esptool and zopfli Python helpers are installed from the same
constrained host requirements. These unmodified host tools are installed
separately; they are not claimed as project-authored code or included in the
firmware source ZIPs. Platform/framework archive integrity does not make every
remote host-tool download hermetic or independently security-audited.

The compiler executable is a host tool; the `libgcc`/`libstdc++` target runtime
code linked into the image is a separate component. GCC 4.8.2 supplies that code
under GPL terms with the GCC Runtime Library Exception 3.1, subject to its eligible
compilation conditions. The original exception text is preserved in
[the project source](../licenses/GCC-RUNTIME-EXCEPTION-3.1.txt), from the
[official GCC 4.8.2 source](https://github.com/gcc-mirror/gcc/blob/releases/gcc-4.8.2/COPYING.RUNTIME).
Do not justify linked runtime code merely by calling the entire toolchain a host
tool or assume that every SDK/library has the same license.

Build timestamps, host architecture and toolchain environment may change image
bytes. Source manifests bind the reviewed inputs and paired source, not a claim of
bit-for-bit reproducibility across all hosts. A release checksum identifies the
actual built artifact. Hosted CI, a local build and an installed-image checksum
remain separate evidence.

Dependency updates require reviewing the lock, source/notices, build output and
relevant upstream security advisories together. This audit does not certify the
absence of vulnerabilities in every upstream component.
