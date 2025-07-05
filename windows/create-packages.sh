#!/bin/bash

set -e

# Source configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

echo "::group::Creating pacman packages"

echo "Building libxml2 package..."
cd "${PACKAGES_DIR}/mingw-w64-clang-x86_64-libxml2"
makepkg --noconfirm --force

echo "Building xmlsec package..."
cd "${PACKAGES_DIR}/mingw-w64-clang-x86_64-xmlsec"
makepkg --noconfirm --force

# Create repository
echo "Creating pacman repository..."
cd "${PACKAGES_DIR}"

# Collect all package files
find . -name "*.pkg.tar.*" -exec cp {} "${DEPLOY_DIR}/" \;

cd "${DEPLOY_DIR}"
repo-add "${REPO_NAME}.db.tar.gz" *.pkg.tar.*

echo "Pacman packages created successfully"
echo "Repository database: ${DEPLOY_DIR}/${REPO_NAME}.db.tar.gz"
echo "Packages in: ${DEPLOY_DIR}/"
echo "::endgroup::"
