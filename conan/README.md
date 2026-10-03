# Conan dependency builds

This is the first stage of replacing the dependency shell scripts with Conan 2.
It builds the dependencies for Workrave's **Qt interface**, cross-compiling
Windows x64 and ARM64 on Linux x64 with llvm-mingw, UCRT and libc++.
The existing macOS and MSYS2 builds remain available during migration.

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
binaries, relocatable CMake metadata and matching PDBs. Unchanged dependency
inputs reuse the exported SDK without running Conan again.

Workrave itself is compiled, packaged with Inno Setup and signed natively in a
Windows Docker container on the `win11-vm` VM. The native Qt image uses the same
llvm-mingw release as these packages. GTK uses a separate MSYS2 image.
See [workrave-build-containers](https://github.com/rcaelers/workrave-build-containers)
for both Windows images, the Linux compiler image and their build commands.

Configure `windows.dependencies_dir`, `windows.dependencies_image` and
`windows.conan_cache` in Workrave's private `ship.yaml` for the Linux SDK job.
`windows.image` selects the Windows GTK image; `windows.qt_image` selects the
native Windows Qt image. `windows.containers_dir` points at that container
repository. Packaging and signing do not use Wine.

## Remaining migration work

* Run the Qt application and a real Crashpad crash on Windows x64 and ARM64.
  Compile/link and PDB identity checks do not prove runtime crash symbolization.
  Qt's officially supported Windows ARM64 compiler is MSVC, so llvm-mingw needs
  our own runtime validation.
* Add the optional gRPC stack and its Workrave AF_UNIX patch/capability marker.
* Migrate macOS separately. Use ordinary arm64 and x86_64 Conan packages, then
  combine the final application during release. This setup does not claim
  universal dependency packages or replace the current universal macOS scripts.

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
