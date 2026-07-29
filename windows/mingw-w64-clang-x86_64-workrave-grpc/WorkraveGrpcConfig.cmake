# Identifies the Workrave gRPC build with MinGW AF_UNIX support and imports the
# regular upstream gRPC targets installed by the same package.

include(CMakeFindDependencyMacro)
find_dependency(gRPC 1.83.0 EXACT CONFIG)

set(WORKRAVE_GRPC_MINGW_AF_UNIX TRUE)
set(WORKRAVE_GRPC_VERSION "1.83.0")
