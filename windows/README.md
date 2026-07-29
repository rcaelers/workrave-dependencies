# Windows dependencies

## Patched gRPC for CLANG64

`build-grpc.sh` creates a pacman package containing static gRPC 1.83.0 with
MinGW AF_UNIX support. It uses Abseil, Protobuf, c-ares, RE2, OpenSSL, and zlib
from the MSYS2 CLANG64 repository.

From an MSYS2 CLANG64 shell with the build dependencies installed:

```sh
bash windows/build-grpc.sh
pacman -U windows/_deploy/workrave-grpc-mingw-clang64.pkg.tar.zst
```

Changes to the build script, package recipe, or workflow publish the same
package as the `windows-grpc-latest` GitHub release asset. Workrave detects the
package through `WorkraveGrpcConfig.cmake`; if it is absent, Workrave retains
its slower source-build fallback.

Install the published package from an MSYS2 CLANG64 shell with:

```sh
curl -fLO https://github.com/rcaelers/workrave-dependencies/releases/download/windows-grpc-latest/workrave-grpc-mingw-clang64.pkg.tar.zst
pacman -U workrave-grpc-mingw-clang64.pkg.tar.zst
```
