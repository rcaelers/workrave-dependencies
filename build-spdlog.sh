#!/usr/bin/env bash -xe

PACKAGE=spdlog
VERSION=v1.14.1

BASEDIR=$(dirname "$0")
source ${BASEDIR}/config.sh

rm -rf ${SOURCEDIR}
rm -rf ${BUILDDIR}
mkdir -p ${DEPLOYDIR} ${SOURCEDIR} ${BUILDDIR}

cd ${SOURCEDIR}
git clone https://github.com/gabime/spdlog.git
cd ${SOURCEDIR}/spdlog
git checkout ${VERSION}

cd ${BUILDDIR}
CMAKE_PREFIX_PATH=${DEPLOYDIR} cmake ${SOURCEDIR}/spdlog -G Ninja -DCMAKE_INSTALL_PREFIX=${DEPLOYDIR} -DCMAKE_OSX_ARCHITECTURES="arm64;x86_64" -DSPDLOG_INSTALL=ON -DSPDLOG_BUILD_SHARED=ON -DSPDLOG_FMT_EXTERNAL=ON -DSPDLOG_WCHAR_TO_UTF8_SUPPORT=ON -DCMAKE_CXX_STANDARD=20 -DCMAKE_OSX_DEPLOYMENT_TARGET="11.0"
cmake --build ${BUILDDIR}
cmake --install ${BUILDDIR}
