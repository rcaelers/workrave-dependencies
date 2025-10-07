#!/usr/bin/env bash -xe

PACKAGE=boost
VERSION=1.89.0

BASEDIR=$(dirname "$0")
source ${BASEDIR}/config.sh

EXTDIR=${ROOTDIR}/_ext/dependencies
if [ ! -d "$EXTDIR" ]; then
    EXTDIR=${DEPLOYDIR}
fi

rm -rf ${SOURCEDIR}/boost_${VERSION_UNDERSCORES}

cd ${SOURCEDIR}
curl -OL https://archives.boost.io/release/${VERSION}/source/boost_${VERSION_UNDERSCORES}.7z
7z x ${SOURCEDIR}/boost_${VERSION_UNDERSCORES}.7z

cd ${SOURCEDIR}/boost_${VERSION_UNDERSCORES}
./bootstrap.sh --prefix=${DEPLOYDIR} --with-icu=${EXTDIR}
./b2 --prefix=${DEPLOYDIR} --user-config=${ROOTDIR}/boost/user-config.jam -sNO_ZSTD=1 -sNO_LZMA=1 -sICU_PATH=${EXTDIR} address-model=64 architecture=arm+x86 threading=multi link=shared abi=sysv binary-format=mach-o pch=off install
