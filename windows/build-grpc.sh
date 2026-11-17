#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd "$(dirname "$0")" && pwd)
package_dir="${script_dir}/mingw-w64-clang-x86_64-workrave-grpc"
deploy_dir="${script_dir}/_deploy"

mapfile -t package_paths < <(cd "${package_dir}" && makepkg --packagelist)
if [[ ${#package_paths[@]} -ne 3 ]]; then
  echo "Expected the upstream grpc, python-grpcio and python-grpcio-tools packages" >&2
  exit 1
fi
(cd "${package_dir}" && makepkg --cleanbuild --noconfirm --force)

mkdir -p "${deploy_dir}"
for package_path in "${package_paths[@]}"; do
  case "$(basename "${package_path}")" in
    *-python-grpcio-tools-*) artifact=workrave-python-grpcio-tools-mingw-clang64.pkg.tar.zst ;;
    *-python-grpcio-*) artifact=workrave-python-grpcio-mingw-clang64.pkg.tar.zst ;;
    *-grpc-*) artifact=workrave-grpc-mingw-clang64.pkg.tar.zst ;;
    *) echo "Unexpected package: ${package_path}" >&2; exit 1 ;;
  esac
  install -Dm644 "${package_path}" "${deploy_dir}/${artifact}"
done
