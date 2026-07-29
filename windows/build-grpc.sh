#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd "$(dirname "$0")" && pwd)
package_dir="${script_dir}/mingw-w64-clang-x86_64-workrave-grpc"
deploy_dir="${script_dir}/_deploy"

package_path=$(cd "${package_dir}" && makepkg --packagelist)
(cd "${package_dir}" && makepkg --noconfirm --force)

mkdir -p "${deploy_dir}"
install -Dm644 "${package_path}" "${deploy_dir}/workrave-grpc-mingw-clang64.pkg.tar.zst"
