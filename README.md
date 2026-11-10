# Workrave dependencies

[Conan 2 builds](conan/README.md) provide the Qt dependency SDKs:

- macOS: native builds exported as a relocatable universal arm64+x86_64 SDK.
- Windows: Linux cross-builds with llvm-mingw, including matching debug symbols.

Start with [`conan/README.md`](conan/README.md) for build and consumer instructions.
The macOS release workflow uses Conan; the older macOS shell builds are retired.

Windows Conan gRPC includes MinGW AF_UNIX support and the Workrave CMake
capability marker. The standalone [MSYS2 CLANG64 gRPC package build](windows/README.md)
is also available for consumers using MSYS2 dependencies. 
