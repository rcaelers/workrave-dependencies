cmake_minimum_required(VERSION 3.21)
project(workrave_dependencies_smoke LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Svg Xml Quick QuickControls2 QuickWidgets LinguistTools)
find_package(Boost REQUIRED COMPONENTS date_time program_options serialization)
find_package(OpenSSL REQUIRED)
find_package(fmt REQUIRED)
find_package(spdlog REQUIRED)
find_package(SQLite3 REQUIRED)
find_package(GTest REQUIRED)
option(WORKRAVE_SMOKE_GTEST_ASAN "Check prebuilt GoogleTest with an instrumented consumer" OFF)
if(WORKRAVE_SMOKE_GTEST_ASAN)
  add_executable(dependencies-gtest-asan gtest-asan.cpp)
  set_target_properties(dependencies-gtest-asan PROPERTIES AUTOMOC OFF AUTORCC OFF)
  target_link_libraries(dependencies-gtest-asan PRIVATE GTest::gtest_main)
  target_compile_options(dependencies-gtest-asan PRIVATE -O0 -g -UNDEBUG
    -fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=undefined)
  target_link_options(dependencies-gtest-asan PRIVATE -fsanitize=address,undefined)
endif()
option(WORKRAVE_SMOKE_DBUS "Check the macOS release's QtDBus dependency" OFF)
if(WORKRAVE_SMOKE_DBUS)
  find_package(Qt6DBus CONFIG REQUIRED)
endif()
option(WORKRAVE_SMOKE_GRPC "Check gRPC libraries and native code generators" OFF)
if(WORKRAVE_SMOKE_GRPC)
  find_package(Protobuf CONFIG REQUIRED)
  if(WIN32 AND MINGW)
    find_package(WorkraveGrpc CONFIG REQUIRED)
    if(NOT WORKRAVE_GRPC_MINGW_AF_UNIX)
      message(FATAL_ERROR "The MinGW gRPC package does not declare AF_UNIX support")
    endif()
    add_executable(dependencies-grpc-af-unix grpc-af-unix.cpp)
    set_target_properties(dependencies-grpc-af-unix PROPERTIES AUTOMOC OFF AUTORCC OFF)
    target_link_libraries(dependencies-grpc-af-unix PRIVATE gRPC::grpc++)
    install(TARGETS dependencies-grpc-af-unix RUNTIME DESTINATION bin)
  else()
    find_package(gRPC CONFIG REQUIRED)
  endif()
endif()
if(WORKRAVE_SMOKE_SDK_ROOT)
  foreach(dependency Qt6 Qt6Core Qt6DBus Boost fmt spdlog Protobuf gRPC SQLite3 OpenSSL GTest ZLIB)
    if(DEFINED ${dependency}_DIR AND NOT "${${dependency}_DIR}" MATCHES "-NOTFOUND$")
      cmake_path(IS_PREFIX WORKRAVE_SMOKE_SDK_ROOT "${${dependency}_DIR}" NORMALIZE in_sdk)
      if(NOT in_sdk)
        message(FATAL_ERROR "${dependency} configuration escaped the SDK: ${${dependency}_DIR}")
      endif()
    endif()
  endforeach()
endif()

qt_add_executable(dependencies-smoke WIN32 MACOSX_BUNDLE main.cpp resources.qrc)
target_link_libraries(dependencies-smoke PRIVATE
  Qt6::Core Qt6::Gui Qt6::GuiPrivate Qt6::Widgets Qt6::Svg Qt6::Xml
  Qt6::Quick Qt6::QuickControls2 Qt6::QuickWidgets
  Boost::date_time Boost::program_options Boost::serialization
  OpenSSL::SSL OpenSSL::Crypto fmt::fmt spdlog::spdlog SQLite::SQLite3 GTest::gtest)
if(WORKRAVE_SMOKE_DBUS)
  target_link_libraries(dependencies-smoke PRIVATE Qt6::DBus)
  target_compile_definitions(dependencies-smoke PRIVATE WORKRAVE_SMOKE_DBUS)
endif()
if(WORKRAVE_SMOKE_GRPC)
  target_link_libraries(dependencies-smoke PRIVATE gRPC::grpc++ protobuf::libprotobuf)
  target_compile_definitions(dependencies-smoke PRIVATE WORKRAVE_SMOKE_GRPC)
  add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/probe.pb.cc" "${CMAKE_CURRENT_BINARY_DIR}/probe.pb.h"
    "${CMAKE_CURRENT_BINARY_DIR}/probe.grpc.pb.cc" "${CMAKE_CURRENT_BINARY_DIR}/probe.grpc.pb.h"
    COMMAND protobuf::protoc --proto_path=${CMAKE_CURRENT_SOURCE_DIR}
      --cpp_out=${CMAKE_CURRENT_BINARY_DIR} --grpc_out=${CMAKE_CURRENT_BINARY_DIR}
      --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>
      "${CMAKE_CURRENT_SOURCE_DIR}/probe.proto"
    DEPENDS probe.proto protobuf::protoc gRPC::grpc_cpp_plugin VERBATIM)
  target_sources(dependencies-smoke PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/probe.pb.cc"
    "${CMAKE_CURRENT_BINARY_DIR}/probe.grpc.pb.cc")
  target_include_directories(dependencies-smoke PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
endif()

# lrelease must run on the build machine, just like AUTOMOC/AUTORCC tools.
add_custom_command(OUTPUT translations.qm
  COMMAND Qt::lrelease "${CMAKE_CURRENT_SOURCE_DIR}/translations.ts" -qm translations.qm
  DEPENDS translations.ts)
add_custom_target(translations ALL DEPENDS translations.qm)

install(TARGETS dependencies-smoke RUNTIME DESTINATION bin BUNDLE DESTINATION .)
