# Workrave dependencies

[Conan 2 builds](conan/README.md) provide the Qt dependency SDKs:

- macOS: native builds exported as a relocatable universal arm64+x86_64 SDK.
- Windows: Linux cross-builds with llvm-mingw, including matching debug symbols.

Start with [`conan/README.md`](conan/README.md) for build and consumer instructions.
The macOS release workflow uses Conan; the older macOS shell builds are retired.

Windows gRPC includes MinGW AF_UNIX support and the Workrave CMake capability
marker. The old MSYS2 gRPC and xmlsec builds are retired; xmlsec is no longer
required.
