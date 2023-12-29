#!/usr/bin/env bash -xe

PACKAGE=boost
VERSION=1.84.0

BASEDIR=$(dirname "$0")
source ${BASEDIR}/config.sh

rm -rf ${SOURCEDIR}/boost_${VERSION_UNDERSCORES}

cd ${SOURCEDIR}
curl -OL https://boostorg.jfrog.io/artifactory/main/release/${VERSION}/source/boost_${VERSION_UNDERSCORES}.7z
7z x ${SOURCEDIR}/boost_${VERSION_UNDERSCORES}.7z

cd ${SOURCEDIR}/boost_${VERSION_UNDERSCORES}
patch -p0 < ${ROOTDIR}/boost/arm+x86.patch
./bootstrap.sh --prefix=${DEPLOYDIR} --with-icu=${DEPLOYDIR}
./b2 --prefix=${DEPLOYDIR} --user-config=${ROOTDIR}/boost/user-config.jam -sNO_ZSTD=1 -sNO_LZMA=1 -sICU_PATH=${DEPLOYDIR} address-model=64 architecture=arm+x86 threading=multi link=shared abi=sysv binary-format=mach-o pch=off install
