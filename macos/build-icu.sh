#!/usr/bin/env bash -xe

PACKAGE=icu
VERSION=78.3

BASEDIR=$(dirname "$0")
source ${BASEDIR}/config.sh

export CMAKE_PREFIX_PATH=/opt/homebrew/opt/llvm/lib

cd ${SOURCEDIR}
if [ ! -d icu ]; then
    git clone https://github.com/unicode-org/icu.git
fi
cd ${SOURCEDIR}/icu
git fetch origin --tags
git checkout release-${VERSION}

rm -rf ${BUILDDIR}
mkdir -p ${BUILDDIR}

cd ${BUILDDIR}
CFLAGS="-arch x86_64 -arch arm64 -mmacosx-version-min=11.0" \
CXXFLAGS="-std=c++20 -arch x86_64 -arch arm64 -mmacosx-version-min=11.0" \
LDFLAGS="-headerpad_max_install_names -mmacosx-version-min=11.0" \
    ${SOURCEDIR}/icu/icu4c/source/runConfigureICU MacOSX \
        --prefix ${DEPLOYDIR} \
        --disable-samples \
        --disable-tests \
        --enable-static \
        --with-library-bits=64 \

make -j$(sysctl -n hw.ncpu)
make install
