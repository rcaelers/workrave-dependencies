ROOTDIR=`pwd`

DEPLOYDIR=${ROOTDIR}/_deploy/dependencies
SOURCEDIR=${ROOTDIR}/_source/${PACKAGE}
BUILDDIR=${ROOTDIR}/_build/${PACKAGE}

VERSION_UNDERSCORES=`echo ${VERSION} | sed -e 's/\./_/g'`

mkdir -p ${DEPLOYDIR} ${SOURCEDIR} ${BUILDDIR}
