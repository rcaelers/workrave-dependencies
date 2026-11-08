# Windows dependencies

[Conan](../conan/README.md) builds the Qt dependency SDK on Linux using
llvm-mingw, with x64/ARM64 profiles and matching PDB archives. Both profiles
include static gRPC with MinGW AF_UNIX support. `WorkraveGrpcConfig.cmake`
provides the capability marker used by Workrave when cross-compiling.

The MSYS2 gRPC patch is now also provided by the Conan recipe overlay.
xmlsec is no longer required. Their package scripts and workflows will be retired at release cutover.

See [workrave-build-containers](https://github.com/rcaelers/workrave-build-containers)
for the MSYS2 GTK and native llvm-mingw/Conan Qt images used by Workrave's
release pipeline. Both compile and package Workrave on Windows; the Qt
dependency SDK is built and cached separately on Linux.
