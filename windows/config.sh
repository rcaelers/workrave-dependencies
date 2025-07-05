#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export BUILD_TYPE=Release
export MINGW_ARCH=x86_64
export MINGW_PREFIX=/clang64

export PACKAGES_DIR="${SCRIPT_DIR}/_packages"
mkdir -p  "${PACKAGES_DIR}"

export PACKAGER="Workrave <rob.caelers@gmail.com>"
export REPO_NAME="workrave-mingw"

echo "Windows build configuration loaded"
echo "PACKAGES_DIR: ${PACKAGES_DIR}"
