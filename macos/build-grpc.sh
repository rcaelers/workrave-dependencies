#!/usr/bin/env bash -xe

PACKAGE=grpc
VERSION=v1.83.0

BASEDIR=$(dirname "$0")
source ${BASEDIR}/config.sh

# Needs OpenSSL: _ext/dependencies when CI downloaded it as a separate job's
# artifact, falling back to _deploy/dependencies for a local sequential build
# where every script installs into (and finds prior packages in) the same
# directory — see build-boost.sh for the same pattern.
EXTDIR=${ROOTDIR}/_ext/dependencies
if [ ! -d "$EXTDIR" ]; then
    EXTDIR=${DEPLOYDIR}
fi

rm -rf ${BUILDDIR}
mkdir -p ${DEPLOYDIR} ${SOURCEDIR} ${BUILDDIR}

cd ${SOURCEDIR}
if [ ! -d grpc ]; then
    git clone https://github.com/grpc/grpc.git
fi
cd ${SOURCEDIR}/grpc
git fetch origin --tags
git checkout ${VERSION}
# Pulls in gRPC's own pinned, mutually-compatible Protobuf/Abseil/c-ares/re2
# checkouts under third_party/ — building all of them together in this one
# CMake configure (via the *_PROVIDER=module flags below) is what guarantees
# they end up ABI/version-compatible with each other, instead of pairing
# gRPC against a separately-built Protobuf that might not match what this
# gRPC release actually expects.
git submodule update --init --recursive

cd ${BUILDDIR}
CMAKE_PREFIX_PATH="${DEPLOYDIR};${EXTDIR}" cmake ${SOURCEDIR}/grpc -G Ninja \
  -DCMAKE_INSTALL_PREFIX=${DEPLOYDIR} \
  -DCMAKE_OSX_ARCHITECTURES="arm64;x86_64" \
  -DCMAKE_OSX_DEPLOYMENT_TARGET="11.0" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_STANDARD=20 \
  -DBUILD_SHARED_LIBS=OFF \
  -DgRPC_INSTALL=ON \
  -DgRPC_BUILD_TESTS=OFF \
  -DgRPC_BUILD_CSHARP_EXT=OFF \
  -DgRPC_BUILD_GRPC_CSHARP_PLUGIN=OFF \
  -DgRPC_BUILD_GRPC_NODE_PLUGIN=OFF \
  -DgRPC_BUILD_GRPC_OBJECTIVE_C_PLUGIN=OFF \
  -DgRPC_BUILD_GRPC_PHP_PLUGIN=OFF \
  -DgRPC_BUILD_GRPC_PYTHON_PLUGIN=OFF \
  -DgRPC_BUILD_GRPC_RUBY_PLUGIN=OFF \
  -DgRPC_SSL_PROVIDER=package \
  -DOPENSSL_ROOT_DIR=${EXTDIR} \
  -DgRPC_ZLIB_PROVIDER=package \
  -DgRPC_PROTOBUF_PROVIDER=module \
  -Dprotobuf_INSTALL=ON \
  -Dprotobuf_BUILD_TESTS=OFF \
  -DgRPC_ABSL_PROVIDER=module \
  -DgRPC_CARES_PROVIDER=module \
  -DgRPC_RE2_PROVIDER=module
cmake --build ${BUILDDIR}
cmake --install ${BUILDDIR}
