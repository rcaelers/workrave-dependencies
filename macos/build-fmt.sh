#!/usr/bin/env bash -xe

PACKAGE=fmt
VERSION=12.1.0

BASEDIR=$(dirname "$0")
source ${BASEDIR}/config.sh

cd ${SOURCEDIR}
if [ ! -f fmt-${VERSION}.zip ]; then
    curl -OL https://github.com/fmtlib/fmt/releases/download/${VERSION}/fmt-${VERSION}.zip
fi
if [ ! -d fmt-${VERSION} ]; then
    unzip fmt-${VERSION}.zip
fi

cd ${BUILDDIR}
cmake ${SOURCEDIR}/fmt-${VERSION} -G Ninja -DCMAKE_INSTALL_PREFIX=${DEPLOYDIR} -DCMAKE_OSX_ARCHITECTURES="arm64;x86_64" -DBUILD_SHARED_LIBS=TRUE -DCMAKE_CXX_STANDARD=20 -DCMAKE_OSX_DEPLOYMENT_TARGET="11.0"
cmake --build ${BUILDDIR}
cmake --install ${BUILDDIR}
