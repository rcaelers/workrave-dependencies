cmake_minimum_required(VERSION 3.21)
project(workrave_grpc_smoke LANGUAGES CXX)

find_package(WorkraveGrpc CONFIG REQUIRED)

add_executable(grpc-af-unix ../../conan/smoke/grpc-af-unix.cpp)
target_compile_features(grpc-af-unix PRIVATE cxx_std_20)
target_link_libraries(grpc-af-unix PRIVATE gRPC::grpc++)

enable_testing()
add_test(NAME grpc-af-unix COMMAND grpc-af-unix)
set_tests_properties(grpc-af-unix PROPERTIES TIMEOUT 30)
