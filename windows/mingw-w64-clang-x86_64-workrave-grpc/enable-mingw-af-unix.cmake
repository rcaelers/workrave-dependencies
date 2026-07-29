# Enable the Windows AF_UNIX implementation already present in gRPC when the
# library is compiled with MinGW. Current MinGW-w64 provides the required API,
# but gRPC 1.83.0 disables it and assumes definitions from the Windows SDK.

if(NOT DEFINED GRPC_SOURCE_DIR)
  message(FATAL_ERROR "GRPC_SOURCE_DIR was not provided")
endif()

set(_grpc_port_header "${GRPC_SOURCE_DIR}/src/core/lib/iomgr/port.h")
if(NOT EXISTS "${_grpc_port_header}")
  message(FATAL_ERROR "gRPC platform header not found: ${_grpc_port_header}")
endif()

file(READ "${_grpc_port_header}" _grpc_port_contents)
set(_grpc_mingw_guard
  "#define GRPC_WINSOCK_SOCKET 1\n#ifndef __MINGW32__\n#define GRPC_HAVE_UNIX_SOCKET 1\n#endif  // __MINGW32__")
set(_grpc_unix_socket_enabled
  "#define GRPC_WINSOCK_SOCKET 1\n#define GRPC_HAVE_UNIX_SOCKET 1")

string(FIND "${_grpc_port_contents}" "${_grpc_mingw_guard}" _grpc_guard_position)
if(NOT _grpc_guard_position EQUAL -1)
  string(REPLACE
    "${_grpc_mingw_guard}"
    "${_grpc_unix_socket_enabled}"
    _grpc_port_contents
    "${_grpc_port_contents}")
  file(WRITE "${_grpc_port_header}" "${_grpc_port_contents}")
  message(STATUS "Enabled gRPC Windows AF_UNIX support for MinGW")
else()
  string(FIND "${_grpc_port_contents}" "${_grpc_unix_socket_enabled}" _grpc_enabled_position)
  if(_grpc_enabled_position EQUAL -1)
    message(FATAL_ERROR
      "The gRPC MinGW AF_UNIX guard no longer matches the audited source. "
      "Review ${_grpc_port_header} before updating gRPC.")
  endif()
  message(STATUS "gRPC Windows AF_UNIX support was already enabled")
endif()

# gRPC includes ws2def.h before afunix.h. That is sufficient with the Windows
# SDK, but MinGW-w64's intentionally minimal ws2def.h does not declare
# ADDRESS_FAMILY; its winsock2.h does. Patch every audited AF_UNIX include site
# to use the complete MinGW Winsock declarations.
set(_grpc_af_unix_sources
  "src/core/lib/address_utils/parse_address.cc"
  "src/core/lib/address_utils/sockaddr_utils.cc"
  "src/core/lib/event_engine/posix_engine/set_socket_dualstack.cc"
  "src/core/lib/event_engine/posix_engine/tcp_socket_utils.cc"
  "src/core/lib/event_engine/tcp_socket_utils.cc"
  "src/core/lib/event_engine/windows/windows_listener.h"
  "src/core/lib/iomgr/unix_sockets_posix.cc")
set(_grpc_windows_sdk_headers "#include <ws2def.h>\n#include <afunix.h>")
set(_grpc_mingw_headers "#include <winsock2.h>\n#include <afunix.h>")

foreach(_grpc_relative_source IN LISTS _grpc_af_unix_sources)
  set(_grpc_source "${GRPC_SOURCE_DIR}/${_grpc_relative_source}")
  if(NOT EXISTS "${_grpc_source}")
    message(FATAL_ERROR "gRPC AF_UNIX source not found: ${_grpc_source}")
  endif()

  file(READ "${_grpc_source}" _grpc_source_contents)
  string(FIND "${_grpc_source_contents}" "${_grpc_windows_sdk_headers}" _grpc_headers_position)
  if(NOT _grpc_headers_position EQUAL -1)
    string(REPLACE
      "${_grpc_windows_sdk_headers}"
      "${_grpc_mingw_headers}"
      _grpc_source_contents
      "${_grpc_source_contents}")
    file(WRITE "${_grpc_source}" "${_grpc_source_contents}")
  else()
    string(FIND "${_grpc_source_contents}" "${_grpc_mingw_headers}" _grpc_headers_position)
    if(_grpc_headers_position EQUAL -1)
      message(FATAL_ERROR
        "The gRPC AF_UNIX includes no longer match the audited source. "
        "Review ${_grpc_source} before updating gRPC.")
    endif()
  endif()
endforeach()

message(STATUS "Enabled MinGW Winsock declarations for gRPC AF_UNIX sources")
