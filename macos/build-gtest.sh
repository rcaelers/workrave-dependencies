#!/usr/bin/env bash -xe

PACKAGE=gtest
VERSION=v1.17.0

BASEDIR=$(dirname "$0")
source ${BASEDIR}/config.sh

rm -rf ${BUILDDIR}
mkdir -p ${DEPLOYDIR} ${SOURCEDIR} ${BUILDDIR}

cd ${SOURCEDIR}
if [ ! -d googletest ]; then
    git clone https://github.com/google/googletest.git
fi
cd ${SOURCEDIR}/googletest
git fetch origin --tags
git checkout ${VERSION}

cd ${BUILDDIR}
cmake ${SOURCEDIR}/googletest -G Ninja -DCMAKE_INSTALL_PREFIX=${DEPLOYDIR} -DCMAKE_OSX_ARCHITECTURES="arm64;x86_64" -DCMAKE_OSX_DEPLOYMENT_TARGET="11.0" -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_STANDARD=20 -DBUILD_GMOCK=ON -DINSTALL_GTEST=ON -DBUILD_SHARED_LIBS=OFF
cmake --build ${BUILDDIR}
cmake --install ${BUILDDIR}
