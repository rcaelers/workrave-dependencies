# Windows dependencies

## Linux cross-build with Conan

See [`conan/README.md`](../conan/README.md) for the Qt dependency build
using llvm-mingw on Linux, with x64/ARM64 profiles and matching PDB archives.

## Native Windows build containers

See [workrave-build-containers](https://github.com/rcaelers/workrave-build-containers)
for the MSYS2 GTK and
native llvm-mingw/Conan Qt images used by Workrave's release pipeline. Both
compile and package Workrave on Windows; the Qt dependency SDK is built and
cached separately on Linux.

## Patched gRPC for CLANG64

`build-grpc.sh` builds the complete [MSYS2 gRPC 1.85.0-4 recipe](https://github.com/msys2/MINGW-packages/tree/19bc2e031e82780357983bf8f28b1fdf7615496e/mingw-w64-grpc)
for CLANG64, including shared libraries, Python bindings and Python code
creation tools. All six upstream patches, dependencies and build options are
preserved. The only local additions enable MinGW AF_UNIX sockets and install
`WorkraveGrpcConfig.cmake` to advertise that capability.

The resulting pacman packages retain the upstream names:

- `mingw-w64-clang-x86_64-grpc`
- `mingw-w64-clang-x86_64-python-grpcio`
- `mingw-w64-clang-x86_64-python-grpcio-tools`

The release filenames have a `workrave-` prefix to distinguish these socket-enabled
builds. They replace the corresponding MSYS2 packages. When migrating from the
older static `mingw-w64-clang-x86_64-workrave-grpc` package, remove that package
before installing these packages to avoid file conflicts.

From an MSYS2 CLANG64 shell with the upstream build dependencies installed:

```sh
bash windows/build-grpc.sh
pacman -U windows/_deploy/*.pkg.tar.zst
```

The workflow installs all three finished packages, links a C++ consumer, tests
C++ and Python Unix socket connections, and exercises the Python code generator
before publishing the packages as the `windows-grpc-latest` release assets.

Install the published packages from an MSYS2 CLANG64 shell with:

```sh
for package in grpc python-grpcio python-grpcio-tools; do
  curl -fLO "https://github.com/rcaelers/workrave-dependencies/releases/download/windows-grpc-latest/workrave-${package}-mingw-clang64.pkg.tar.zst"
done
pacman -U workrave-*-mingw-clang64.pkg.tar.zst
```

Reconfigure Workrave in a fresh build directory after switching from static to
shared gRPC so its cached library paths are not reused. Keep the CLANG64 `bin`
directory on `PATH` when running consumers of the shared libraries. As with
upstream MSYS2 packages, incompatible dependency upgrades require a rebuild;
the socket patch does not provide additional OpenSSL compatibility.

Workrave finds the package through `WorkraveGrpcConfig.cmake`. Native builds
verify Unix socket support by running a listener probe. Cross builds use the
capability marker because they cannot run the Windows executable.
