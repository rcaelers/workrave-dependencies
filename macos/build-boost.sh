#!/usr/bin/env bash -xe

PACKAGE=boost
VERSION=1.91.0

BASEDIR=$(dirname "$0")
source ${BASEDIR}/config.sh

JOBS=$(sysctl -n hw.ncpu)

rm -rf ${SOURCEDIR}/boost_${VERSION_UNDERSCORES}

cd ${SOURCEDIR}
if [ ! -f boost_${VERSION_UNDERSCORES}.7z ]; then
    curl -OL https://archives.boost.io/release/${VERSION}/source/boost_${VERSION_UNDERSCORES}.7z
fi
7z x -y ${SOURCEDIR}/boost_${VERSION_UNDERSCORES}.7z

cd ${SOURCEDIR}/boost_${VERSION_UNDERSCORES}
# Build the full library set (most are header-only or cheap to compile) —
# only mpi and python are excluded, since they need an external MPI
# implementation / Python dev headers respectively that nothing here uses.
./bootstrap.sh --prefix=${DEPLOYDIR} --without-libraries=mpi,python
# Boost.Locale and Boost.Regex both auto-probe for a system ICU at build
# time and silently link against whatever they find on the machine (no
# flag needed to enable it, only to disable it) — force both off explicitly
# so the build never depends on whatever happens to be installed locally
# (e.g. a non-universal Homebrew ICU), matching the same universal
# arm64+x86_64 binary this build otherwise guarantees everywhere else.
./b2 -j${JOBS} --prefix=${DEPLOYDIR} --user-config=${ROOTDIR}/boost/user-config.jam -sNO_ZSTD=1 -sNO_LZMA=1 --disable-icu boost.locale.icu=off address-model=64 architecture=arm+x86 threading=multi link=shared abi=sysv binary-format=mach-o pch=off install
