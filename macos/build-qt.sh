#!/usr/bin/env bash -xe

PACKAGE=qt
VERSION=6.11

BASEDIR=$(dirname "$0")
source ${BASEDIR}/config.sh

export CMAKE_PREFIX_PATH=/opt/homebrew/opt/llvm/lib

cd ${SOURCEDIR}
if [ ! -d qt6 ]; then
    git clone git://code.qt.io/qt/qt5.git qt6
fi
cd ${SOURCEDIR}/qt6
git fetch origin --tags
git checkout ${VERSION}
perl ./init-repository -f --module-subset=qtbase,qtdeclarative,qtimageformats,qtsvg,qttools,qttranslations

rm -rf ${BUILDDIR}
mkdir -p ${BUILDDIR}

export PKG_CONFIG_PATH="${DEPLOYDIR}/lib/pkgconfig"
export DYLD_LIBRARY_PATH="${DEPLOYDIR}/lib"

cd ${BUILDDIR}
${SOURCEDIR}/qt6/configure \
    -prefix ${DEPLOYDIR} \
    -release \
    -opensource \
    -confirm-license \
    -nomake examples \
    -nomake tests \
    -no-feature-relocatable \
    -rpath \
    -c++std c++23 \
    -no-icu \
    --  \
    -G Ninja \
    -Wno-dev \
    -DCMAKE_INSTALL_PREFIX=${DEPLOYDIR} \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_FIND_FRAMEWORK=FIRST \
    -DCMAKE_VERBOSE_MAKEFILE=ON \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=11.0 \
    -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64"

cmake --build .
cmake --install .
