# Enable gRPC's Windows AF_UNIX implementation with current MinGW-w64 headers.
# Keep each source change idempotent and reject unexpected upstream layouts.
if(NOT DEFINED GRPC_SOURCE_DIR)
  message(FATAL_ERROR "GRPC_SOURCE_DIR was not provided")
endif()

function(workrave_grpc_replace relative_source original replacement)
  set(source "${GRPC_SOURCE_DIR}/${relative_source}")
  file(READ "${source}" contents)
  string(FIND "${contents}" "${replacement}" patched)
  if(NOT patched EQUAL -1)
    return()
  endif()
  string(FIND "${contents}" "${original}" found)
  if(found EQUAL -1)
    message(FATAL_ERROR "gRPC no longer matches the audited source: ${source}")
  endif()
  string(REPLACE "${original}" "${replacement}" contents "${contents}")
  file(WRITE "${source}" "${contents}")
endfunction()

# gRPC 1.84 disables AF_UNIX for MinGW despite the required API being available.
workrave_grpc_replace("src/core/lib/iomgr/port.h"
  "#define GRPC_WINSOCK_SOCKET 1\n#ifndef __MINGW32__\n#define GRPC_HAVE_UNIX_SOCKET 1\n#endif  // __MINGW32__"
  "#define GRPC_WINSOCK_SOCKET 1\n#define GRPC_HAVE_UNIX_SOCKET 1")
message(STATUS "Enabled gRPC Windows AF_UNIX support for MinGW")

# MinGW's minimal ws2def.h does not declare ADDRESS_FAMILY; winsock2.h does.
foreach(source IN ITEMS
    src/core/lib/address_utils/parse_address.cc
    src/core/lib/address_utils/sockaddr_utils.cc
    src/core/lib/event_engine/posix_engine/set_socket_dualstack.cc
    src/core/lib/event_engine/posix_engine/tcp_socket_utils.cc
    src/core/lib/event_engine/tcp_socket_utils.cc
    src/core/lib/event_engine/windows/windows_listener.h
    src/core/lib/iomgr/unix_sockets_posix.cc)
  workrave_grpc_replace("${source}"
    "#include <ws2def.h>\n#include <afunix.h>"
    "#include <winsock2.h>\n#include <afunix.h>")
endforeach()
message(STATUS "Enabled MinGW Winsock declarations for gRPC AF_UNIX sources")

# ARM64's Windows headers do not transitively provide abort().
workrave_grpc_replace("src/core/util/windows/env.cc"
  "#include <grpc/support/port_platform.h>"
  "#include <grpc/support/port_platform.h>\n#include <stdlib.h>")

# Backport protobuf #24897 to gRPC's bundled UPB. Alignment inside a function
# breaks LLVM's Windows ARM64 SEH generation. Keep assembly and unwind support.
workrave_grpc_replace("third_party/upb/upb/wire/encode.c"
  "      \".p2align \" UPB_BTI_SHIFT_IMM"
  "      #ifndef __SEH__\n      \".p2align \" UPB_BTI_SHIFT_IMM\n      #endif")
