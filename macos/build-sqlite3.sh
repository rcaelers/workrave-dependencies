#!/usr/bin/env bash -xe

PACKAGE=sqlite3
VERSION=3.53.4
RELEASE_YEAR=2026

BASEDIR=$(dirname "$0")
source ${BASEDIR}/config.sh

JOBS=$(sysctl -n hw.ncpu)

rm -rf ${BUILDDIR}
mkdir -p ${DEPLOYDIR} ${SOURCEDIR} ${BUILDDIR}

# sqlite.org tarballs encode the version as 7 digits (3.53.4 -> 3530400)
# and live in a directory named after the release year.
VERSION_NUM=$(echo ${VERSION} | awk -F. '{ printf "%d%02d%02d00", $1, $2, $3 }')

cd ${SOURCEDIR}
if [ ! -f sqlite-autoconf-${VERSION_NUM}.tar.gz ]; then
    curl -OL https://sqlite.org/${RELEASE_YEAR}/sqlite-autoconf-${VERSION_NUM}.tar.gz
fi
if [ ! -d sqlite-autoconf-${VERSION_NUM} ]; then
    tar xzf sqlite-autoconf-${VERSION_NUM}.tar.gz
fi

cd ${BUILDDIR}
# SQLite is arch-independent C, so a single pass with both -arch flags
# produces universal binaries directly (no per-arch build + lipo needed).
# --disable-readline keeps the sqlite3 shell from linking a Homebrew
# readline/editline on CI runners.
CFLAGS="-arch arm64 -arch x86_64 -mmacosx-version-min=11.0 -Os" \
LDFLAGS="-arch arm64 -arch x86_64 -mmacosx-version-min=11.0" \
    ${SOURCEDIR}/sqlite-autoconf-${VERSION_NUM}/configure --prefix=${DEPLOYDIR} --disable-readline
make -j${JOBS}
make install
