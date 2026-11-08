# Conan dependency builds

Shared Conan 2 recipes build the dependencies for Workrave's **Qt interface**:
Windows x64/ARM64 cross-builds on Linux with llvm-mingw, and native macOS builds
exported as a universal arm64+x86_64 SDK. Use Conan 2.34.0 or newer.
The existing dependency builders remain available during the SDK migration.

## macOS

Install Conan, CMake, Ninja and pkg-config, and select the Xcode installation to
use. From the repository root:

```sh
python3 conan/build.py --platform macos --check
python3 conan/build.py --platform macos --jobs 8
```

The driver selects the native build profile, detects the Apple Clang major and
uses an isolated cache at `conan/_build/conan-home-macos`. Set `CONAN_HOME` to
choose another dedicated cache. `WORKRAVE_APPLE_CLANG` and `WORKRAVE_PKG_CONFIG`
override compiler-major detection and pkg-config discovery. The deployment
target is macOS 14.4 (Sonoma) for both architectures. Runtime validation runs
on the build machine; it does not constitute testing on macOS 14.4 itself.
Qt 6.12 sets this support floor; see the dependency review below.
Qt receives the target explicitly on CMake's command line because its early
platform detection runs before Conan's toolchain is loaded. Export checks the
actual Mach-O minimum OS versions, not just the profile settings.
Qt uses bundled libb2/TIFF/WebP and excludes Homebrew library prefixes and
pkg-config defaults from discovery. Each thin Qt package is checked for
Homebrew linkage before the driver proceeds to the next stage.

The same `conanfile.py` and version selections are used for Windows and macOS.
macOS profiles enable gRPC/Protobuf, QtDBus and a broader Boost library set. Abseil is shared on macOS, matching the original shell build and ensuring
protobuf/gRPC use one synchronization runtime. Static copies in separate dylibs
caused gRPC server startup to stall, including in ASan/UBSan RPC tests.
GoogleTest is also shared on macOS. This keeps its prebuilt STL implementation
separate from sanitizer-instrumented consumers, avoiding mixed vector
annotations during test registration without disabling container checks.
Cobalt is omitted on both platforms: Workrave does not use it and the
upstream Boost 1.91 recipe expects an unconfigured Cobalt SSL library.
OpenSSL uses the current compatible 3.x release because gRPC requires
OpenSSL below version 4. Routine builds use committed, separate platform locks.

The default build compiles each architecture separately, including matching
native Qt/protobuf/gRPC tools for cross-builds. `--arch arm64` or `--arch x86_64`
builds only that slice and its smoke application. `--arch all` (the default)
also exports `conan/_build/macos-universal`; change this with `--sdk-output`.
Build-local protoc/plugin launchers set the native library environment after
macOS SIP's shell filtering. These launchers are not exported: SDK executables
use their own relocated dylib paths and need no Conan environment.
The destination must not exist. Export is transactional and never edits Conan
packages or overwrites an earlier SDK.

The exported SDK uses **Qt dylibs**, not frameworks. Every Mach-O executable,
dylib, plugin and static archive must contain both arm64 and x86_64 slices.
Generated headers that differ are selected by the consumer compiler's target
architecture. Unexplained resource/metadata differences fail export rather
than silently choosing one architecture. Dylib identities, dependency paths
and rpaths are rewritten on exported copies, then ad-hoc signed. Application
distribution still requires the existing Developer ID signing/notarization.
Original dylib install-name basenames are retained and all dependency aliases
use those same names, so deployment loads one copy of each library.
Qt's Android/HarmonyOS deployment tools and build-machine host launchers are
omitted from this macOS SDK. CMake/qmake feature inventories advertise common
capabilities; architecture-specific headers retain each slice's definitions.

SDK layout:

* `packages/<name>/`: universal libraries, headers, tools, Qt plugins and QML.
* `generators/`: relocated Conan CMakeDeps configuration and imported targets.
* `lib/cmake/<name>/`: package entry points for standard CMake prefix discovery.
  Qt's individual module names (for example `Qt6DBus`) are supported as well
  as `find_package(Qt6 COMPONENTS ...)`.
* `bin/`: tool symlinks, including `qtpaths`, `macdeployqt`, `protoc`, and
  `grpc_cpp_plugin`. Qt configuration reports paths inside the exported SDK.
* `include/`, `lib/` and Qt resource directories: compatibility symlinks for
  standard prefix searches and deployment tools, without duplicating packages.
* `toolchain.cmake`: optional universal-build defaults.
* `manifest.json`, `macos.lock`: merged packages and resolved recipe references.

Qt's original SPDX inventories are preserved under `packages/qt/sbom/<arch>/`
as input provenance. Their checksums describe the thin packages before merging
and signing, rather than the exported universal binaries.

The macOS GitHub Actions workflow builds this SDK directly with Conan and
publishes `workrave-dependencies-macos.tar.gz`, retaining the `macos-latest`
release contract. PRs build and validate without publishing. Validation utilities
live under `conan/scripts/`; the former `macos/build-*.sh` entry points are retired.

Consumers do not need Conan or the original cache. For example:

```sh
sdk="$PWD/conan/_build/macos-universal"
cmake -S ../workrave-v1_12 -B /tmp/workrave-macos -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$sdk" \
  -DCMAKE_OSX_ARCHITECTURES='arm64;x86_64' \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=14.4 -DWITH_UI=Qt -DWITH_GRPC=ON
```

Alternatively pass `-DCMAKE_TOOLCHAIN_FILE="$sdk/toolchain.cmake"`.
After changing the minimum macOS version, clear the consumer CMake cache
(or explicitly set `CMAKE_OSX_DEPLOYMENT_TARGET=14.4`): cached values override
toolchain defaults. Existing dependencies built for an older macOS minimum
remain usable; rebuild the SDK to compile its packages for 14.4 as well.
The existing release job's `macos.dependencies_dir` can point at the SDK root.
Package contents live under `packages/`; compatibility symlinks also expose
headers/libraries in the familiar `include/` and `lib/` prefix directories.

After export the driver temporarily moves the SDK to a path containing spaces,
checks `qtpaths`, compiles the universal smoke application using only
`CMAKE_PREFIX_PATH`, runs a sanitizer-instrumented GoogleTest registration probe,
deploys its `.app` using the exported `macdeployqt`, checks
architecture/signatures and Homebrew linkage, and loads its Qt Quick component
without showing a window, with the SDK temporarily moved out of reach and Qt/
dynamic-loader path overrides removed from the test environment. This exercises Qt tools, QML imports, native
protoc/gRPC code generation, a real loopback gRPC echo call, QtDBus and dependency linkage on the native architecture;
it does not prove Workrave GUI behavior, Intel runtime on an Apple Silicon
builder, or notarization. To repeat validation or export existing thin builds:

```sh
python3 conan/build.py --platform macos --validate
python3 conan/export-sdk.py --platform macos --output /tmp/workrave-macos-sdk
python3 -m unittest discover -s conan/tests -p test_macos_sdk.py -v
```

The integration test compiles real thin libraries/tools, merges and moves the
SDK, deletes its original Conan cache, then builds and runs a universal CMake
consumer.

To update the macOS graph after changing versions/recipes:

```sh
python3 conan/build.py --platform macos --update-lock
python3 conan/build.py --platform macos --check
```

This locks both target architectures and native tools for both builder
architectures. Rebuild Windows locks in the Linux compiler image as well when
updating shared versions. Review lock changes before committing.

### macOS dependency support review (2026-11-07)

The supported application floor is **macOS 14.4**, determined by Qt 6.12.
Upstream support policy differs from the minimum OS recorded by a successful
local build: compiling Qt with a lower deployment target does not extend its
upstream support. Build-host SDK/compiler requirements are separate again.

| Dependency in the Conan SDK | Upstream macOS support finding |
| --- | --- |
| Qt 6.12.0 | **14.4+**, Intel and Apple Silicon; Xcode 16 / macOS 15 SDK or newer for building. [Qt 6.12 platform matrix](https://doc.qt.io/qt-6.12/supported-platforms.html). |
| GoogleTest 1.18.0, Abseil 20260107.1 | Follow Google's current support policy: **13+ target**, Xcode 27 / Apple Clang 21 build toolchain. This is the current policy, not a historical hard minimum for every release. [GoogleTest](https://google.github.io/googletest/platforms.html), [Abseil](https://abseil.io/about/compatibility), [support matrix](https://github.com/google/oss-policies-info/blob/main/foundational-cxx-support-matrix.md). |
| gRPC 1.84.0, Protobuf 6.33.5, RE2 20251105 | No separate numeric macOS floor found in the pinned source build documentation/recipes; their Abseil dependency brings the policy above. [gRPC build documentation](https://github.com/grpc/grpc/blob/master/BUILDING.md). |
| OpenSSL 3.6.5 | Upstream primary-platform table includes macOS **11** on Intel and Apple Silicon; this is a tested platform, not an explicit oldest-runtime guarantee. [OpenSSL platforms](https://mirror.openssl-library.org/policies/general-supplemental/platforms/). |
| Boost 1.91.0 | No single numeric macOS floor published across all libraries; requirements vary by library and compiler. [Release documentation](https://www.boost.org/releases/1.91.0/). |
| fmt 12.2.0, spdlog 1.17.0 | Compiler requirements rather than a numeric macOS floor. fmt documents C++11 / Clang 3.6+, spdlog documents macOS / Clang 3.5+. [fmt portability](https://fmt.dev/latest/), [spdlog platforms](https://github.com/gabime/spdlog#platforms). |
| SQLite 3.54.1, libxml2 2.15.4, zlib 1.3.2 | No numeric macOS floor found in the pinned source build documentation/recipes. libxml2 documents POSIX support. [libxml2 dependencies](https://github.com/GNOME/libxml2/blob/v2.15.4/README.md#dependencies). |
| c-ares 1.34.9 | Installation documentation lists macOS **10.4+**; older-target feature checks remain in its build. [c-ares installation](https://github.com/c-ares/c-ares/blob/main/INSTALL.md). |
| PCRE2 10.42, bzip2 1.0.8, double-conversion 3.4.0, FreeType 2.15.0, libpng 1.6.59, Brotli 1.2.1, HarfBuzz 15.0.0, D-Bus 1.15.8, Expat 2.10.0, libbacktrace cci.20210118, libiconv 1.17 | No requirement above 14.4 found in the pinned Conan recipes or top-level upstream build documentation. A precise supported macOS minimum is unspecified; this is not a guarantee of support for arbitrary older releases. |
| OpenGL/system | Apple's system framework, not a separately compiled library. |

The legacy macOS scripts also build ICU separately. Conan's Qt profile disables ICU,
so no standalone ICU build is needed for this SDK.
This review concerns deployment OS support, not library release lifetimes or
an upgrade audit. Recheck the upstream matrices when updating dependencies.

## Build

From the repository root on a Linux amd64 Docker or Podman host:

```sh
docker pull ghcr.io/rcaelers/workrave-build:llvm-mingw
docker run --rm \
  -v "$PWD:/work" \
  -v workrave-conan:/cache \
  ghcr.io/rcaelers/workrave-build:llvm-mingw \
  python3 conan/build.py --arch x86_64 --jobs 8 --export-cache
```

Use `--arch arm64` for Windows ARM64, or `--arch all` to build both sequentially.
`podman` can replace `docker` in these commands. With a remote Podman service,
the bind mount must refer to a checkout on that host; alternatively copy the
`conan` directory into a container with `podman cp`.

The image definition lives in `workrave-build-containers/llvm-mingw`.
To build it locally from this repository's root with the adjacent checkout:

```sh
docker build -t ghcr.io/rcaelers/workrave-build:llvm-mingw ../workrave-build-containers/llvm-mingw
```

The image is for **Linux amd64**. On Apple Silicon, use a remote amd64 builder
or pass `--platform linux/amd64` to both Docker commands (which uses emulation).
Reserve substantial disk space for Qt's sources, native tools, target builds
and PDBs. Start with eight jobs; reduce this on machines with less memory.
Do not run simultaneous Conan builds against the same cache volume.
Use `python3 conan/build.py --check` in the image to validate both locked graphs
without compiling packages.

The driver installs project configuration into `/cache/conan`, resolves the
committed lockfile, builds missing packages, then compiles a small Qt application.
That application checks the actual Workrave Qt components, native Linux
`moc`, `rcc` and `lrelease`, and linkage to Boost, OpenSSL, fmt, spdlog and SQLite. The graph also supplies
zlib for Crashpad and libxml2 for the updater.
It is a build check; the Windows application is not executed on Linux.

Outputs in `conan/_build/windows-<arch>/`:

| Output | Purpose |
| --- | --- |
| `build/RelWithDebInfo/generators/` | Conan CMake toolchain and dependency targets |
| `smoke/` | Cross-compiled Qt test application and its PDB |
| `symbols.tar.gz`, `symbols.json` | Dependency PDBs, module identities and binary checksums |
| `runtime/` | Matching llvm-mingw C++/unwind/pthread runtime DLLs |
| `graph.json`, `windows.lock` | Resolved package graph and recipe revisions |
| `conan-cache.tgz` | Optional portable Conan packages, including native Qt tools and PDBs |

The cache archive can be moved to another Linux amd64 builder and restored with
`conan cache restore conan-cache.tgz`, using the same image and configuration.
Then run `build.py` to regenerate CMake files for that machine. Generated CMake
files contain cache paths, so they are not a relocatable SDK by themselves.
Conan keeps unchanged packages between builds; `--export-cache` is only needed
when an archive is wanted. Export includes transitive packages that Conan would
otherwise skip, preserving compatible package selections after a fresh restore.

## Recreate the Forge caches

From the Workrave checkout, using its local ship configuration:

```sh
tools/local/ship release --target windows-dependencies
```

This creates missing Linux Conan and Windows SDK volumes, builds missing
locked Windows amd64 dependencies, checks their PDB identities, and installs
the exported SDK into the Windows VM. It does not build or publish Workrave.
An empty cache is supported; the lockfile is not updated. `scripts_dir` must
point at the Workrave checkout's `tools/` directory.

Set `windows.conan_cache` and `windows.qt_sdk_cache` to choose the volume names.
Repeating the command reuses complete caches. The container images must be
available or built from `workrave-build-containers`; Workrave prepares the
native Windows image automatically when needed.

## Packages and updates

Direct versions are explicit in `conanfile.py`. `windows.lock` pins the full
host/build graph, including transitive versions and recipe revisions. The
compiler release and its SHA-256 are pinned in
`workrave-build-containers/llvm-mingw/Dockerfile`; native tools use
Ubuntu 26.04's GCC 15 and run on Linux. Qt's native and target versions match.
The upstream llvm-mingw archive's `ubuntu-22.04` label describes its build
baseline; the container itself uses Ubuntu 26.04.

Most recipes come directly from ConanCenter. `setup.py` downloads a verified,
pinned ConanCenter snapshot and applies small patches for the exceptions:

* **Boost:** select B2's GNU driver/linker rules for Windows Clang without an
  MSVC runtime. This also produces the required MinGW import libraries.
* **OpenSSL 3:** recognize llvm-mingw and select `mingw64` or `mingwarm64`.
* **Qt:** import the missing native QML tools and versionless tool aliases,
  handle the omitted `windeployqt` in Linux cross-builds, supply a missing
  `<vector>` include in 6.11.1, and use MinGW entry-point metadata for Clang.

`config/workrave/qt-required-modules.cmake` fails configuration if required
Quick modules were silently omitted.

The build enables Qt Base, Declarative, ShaderTools, ImageFormats, SVG, Tools and
Translations (plus their required modules). HarfBuzz and FreeType retain text shaping support;
unneeded GLib, ICU, database drivers and WebEngine are disabled. Boost builds the
Workrave libraries, Unfold updater libraries, Boost.Test, and their required libraries. fmt uses its normal
library interface; its optional C++ module is disabled for libc++ compatibility.

To update, edit direct versions and any relevant patches/compiler settings, then
run in the image:

```sh
python3 conan/build.py --update-lock
python3 conan/build.py --arch all --export-cache
```

Review and commit the changed lockfile. Routine builds do not update it. If a
patch changes, also update the lock so it refers to the newly exported recipe
revision. Update `settings_user.yml` and the profiles when changing LLVM majors.
The `user.workrave:toolchain` configuration participates in target package IDs;
bump it when changing the compiler distribution, compatibility fixes or symbol
policy so old cached packages cannot silently bypass those changes.

## Debug symbols

Windows packages use `RelWithDebInfo`, `-g -gcodeview` and LLD's `--pdb=` option.
A Conan post-package hook saves PDBs after recipes have removed their installed
copies. For every packaged DLL/EXE it verifies the architecture and the PDB
GUID/age against the PE CodeView record. Missing or mismatched symbols fail the
build. Symbols are stored **inside the Conan package** so they survive cache
reuse, export and removal of build directories. Static library debug information
is carried by its object files into the final executable's PDB.

`symbols.tar.gz` is a PDB archive, not a Breakpad symbol store. Use the existing
`dump_syms` pipeline to convert these matching PDBs for Crashpad/Guardrail. No
symbols are uploaded by these build commands. The upstream llvm-mingw runtime
DLLs do not include PDBs; they are listed separately under `runtime/`, outside
the Conan dependency symbol guarantee.

The image includes pinned Linux `dump_syms` 2.3.9. For example, after extracting
the symbol archive, `dump_syms --store /output/breakpad path/to/library.pdb`
creates a Breakpad symbol-store entry.

## Workrave release builds

Workrave's `tools/local/release.yaml` uses this Linux image to build and cache
Windows amd64 Qt dependencies. The `win-qt-sdk` job exports their Windows
binaries, relocatable CMake metadata and matching PDBs. Cache lookup, Conan
configuration/build, the Qt smoke build, PDB validation, SDK export and archive
caching are separate steps in that YAML. Unchanged dependency inputs reuse the
exported SDK without running Conan again.

For Windows, `export-sdk.py` exports an already resolved amd64 dependency graph; it does
not build packages, validate PDBs or manage caches. The workflow first runs
`build.py --arch x86_64 --validate` to check the existing smoke build and every
resolved package's architecture, checksum and PDB identity. SDK CMake files are
kept under `sdk/`, rather than embedded in Python strings.

To export after those build and validation steps:

```sh
python3 conan/export-sdk.py --output /output/windows-sdk --cache-key "$SDK_KEY"
```

The output directory must not already exist. `SDK_KEY` identifies the dependency
inputs and tool versions, as computed by the workflow. Archive creation and
Windows transfer belong to the workflow, not the exporter.

Workrave itself is compiled, packaged with Inno Setup and signed natively in a
Windows Docker container on a configured SSH-accessible Windows host (or on
the machine running Ship itself when that machine runs Windows). The native Qt image uses the same
llvm-mingw release as these packages. GTK uses a separate MSYS2 image.
See [workrave-build-containers](https://github.com/rcaelers/workrave-build-containers)
for both Windows images, the Linux compiler image and their build commands.

Configure `windows.dependencies_dir`, `windows.dependencies_image` and
`windows.conan_cache` in Workrave's private `ship.yaml` for the Linux SDK job.
Keep SSH access and optional VM lifecycle commands in an included environment
configuration (see `tools/local/ship.environments.example.yaml` in Workrave).

`windows.image` selects the Windows GTK image; `windows.qt_image` selects the
native Windows Qt image. `windows.containers_dir` points at that container
repository. Packaging and signing do not use Wine.

## Remaining migration work

* Migrate Windows gRPC and its MinGW AF_UNIX capability marker to Conan.

* Run the Qt application and a real Crashpad crash on Windows x64 and ARM64.
  Compile/link and PDB identity checks do not prove runtime crash symbolization.
  Qt's officially supported Windows ARM64 compiler is MSVC, so llvm-mingw needs
  our own runtime validation.
* The Conan macOS SDK has passed universal build, relocation, deployment and
  Workrave ASan/UBSan test checks on Apple Silicon. Intel runtime, full GUI and
  Developer ID/notarization acceptance remain separate checks.

The GitHub Actions workflow is disabled for now at
`.github/workflows/conan.yaml.disabled`. Remove the `.disabled` suffix to enable
it. The workflow checks both locked graphs and runs PE/PDB preservation tests
using real x64 and ARM64 DLLs. It does not build all of Qt on each PR.
The tests also convert both architectures' PDBs with `dump_syms`, checking the
module identity, function symbols and source filenames.

References: [Conan cross-building](https://docs.conan.io/2/tutorial/consuming_packages/cross_building_with_conan.html),
[Conan hooks](https://docs.conan.io/2/reference/extensions/hooks.html),
[llvm-mingw PDB support](https://github.com/mstorsjo/llvm-mingw#pdb-support),
[Qt Windows support](https://doc.qt.io/qt-6/windows.html).
