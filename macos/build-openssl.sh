#!/usr/bin/env bash -xe

PACKAGE=openssl
VERSION=3.6.0
DYLD_VERSION=3

BASEDIR=$(dirname "$0")
source ${BASEDIR}/config.sh

cd ${SOURCEDIR}
git clone https://github.com/openssl/openssl.git
cd ${SOURCEDIR}/openssl
git checkout openssl-${VERSION}
git clean -fdx

./Configure --prefix=${DEPLOYDIR} --openssldir=${DEPLOYDIR} darwin64-arm64-cc no-ssl3 no-ssl3-method enable-ec_nistp_64_gcc_128 no-weak-ssl-ciphers shared -fPIC -mmacosx-version-min=11.0
make clean
make -j8
make install

./Configure --prefix=${BUILDDIR}/intel --openssldir=${DEPLOYDIR} darwin64-x86_64-cc no-ssl3 no-ssl3-method enable-ec_nistp_64_gcc_128 no-weak-ssl-ciphers shared -fPIC -mmacosx-version-min=11.0
make clean
make -j8
make install

BINARIES="bin/openssl
          lib/libcrypto.${DYLD_VERSION}.dylib 
          lib/libssl.${DYLD_VERSION}.dylib
          lib/libcrypto.a
          lib/libssl.a
          lib/engines-3/capi.dylib
          lib/engines-3/loader_attic.dylib
          lib/engines-3/padlock.dylib
          lib/ossl-modules/legacy.dylib"

for BINARY in ${BINARIES}; do
  lipo -create ${DEPLOYDIR}/${BINARY} ${BUILDDIR}/intel/${BINARY} -output ${DEPLOYDIR}/${BINARY}
done
