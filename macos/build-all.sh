#!/usr/bin/env bash -e

# Runs every build-*.sh script in the order their dependencies require
# (matching .github/workflows/macos.yaml's `needs:` graph: openssl before
# grpc, fmt before spdlog). Everything accumulates into the same
# macos/_deploy/dependencies, exactly as if you'd run each script by hand
# one at a time in this order — this just saves having to remember/re-derive
# that order yourself.
#
# ICU is deliberately not built/installed here: nothing in Workrave uses it
# (no find_package(ICU), no unicode/ includes) and the Boost components
# actually linked (date_time/program_options/serialization/test) don't need
# it either — build-icu.sh is still present if you ever need it back.
#
# After everything builds, check-no-homebrew-links.sh runs automatically to
# verify nothing in _deploy/dependencies picked up a stray Homebrew lib
# (e.g. Boost.Locale/Regex auto-detecting a system ICU) instead of staying
# self-contained.
#
# Usage:
#   ./build-all.sh          # build everything, from openssl onward
#   ./build-all.sh grpc     # skip everything before grpc (assumes
#                           # openssl/boost/fmt/spdlog/gtest are already
#                           # built into _deploy/dependencies from an earlier
#                           # run) — handy for resuming after fixing one
#                           # script without rebuilding everything before it.
#   ./build-all.sh --parallel
#                           # openssl/boost/fmt/gtest/sqlite3/qt have no real
#                           # cross-dependencies (each build-*.sh already
#                           # saturates all cores on its own via Ninja/-j),
#                           # so this only wins if you have enough idle
#                           # cores/memory to run several of those large
#                           # builds (Qt, Boost) at once without thrashing —
#                           # try it and fall back to the sequential default
#                           # if it doesn't actually help on this machine.
#                           # Not combinable with resuming from a package
#                           # name. Output is split into per-package log
#                           # files since it interleaves.

BASEDIR=$(cd "$(dirname "$0")" && pwd)
cd "${BASEDIR}"

ORDER=(openssl boost fmt spdlog gtest sqlite3 grpc qt)

if [ "${1:-}" == "--parallel" ]; then
    LOGDIR=$(mktemp -d "${TMPDIR:-/tmp}/workrave-deps-build.XXXXXX")
    echo "Parallel build — per-package logs in ${LOGDIR}"

    run_stage() {
        local pkgs=("$@")
        echo "=== Building in parallel: ${pkgs[*]} ==="
        local pids=()
        for pkg in "${pkgs[@]}"; do
            ./build-${pkg}.sh >"${LOGDIR}/${pkg}.log" 2>&1 &
            pids+=($!)
        done
        local status=0
        for i in "${!pids[@]}"; do
            if ! wait "${pids[$i]}"; then
                echo "!!! ${pkgs[$i]} failed — see ${LOGDIR}/${pkgs[$i]}.log" >&2
                status=1
            fi
        done
        return ${status}
    }

    # Stage 1: no cross-dependencies among these. Stage 2: spdlog needs fmt,
    # grpc needs openssl — both satisfied once stage 1 finishes.
    run_stage openssl boost fmt gtest sqlite3 qt || exit 1
    run_stage spdlog grpc || exit 1
    ./check-no-homebrew-links.sh
    exit $?
fi

START="${1:-${ORDER[0]}}"

START_INDEX=-1
for i in "${!ORDER[@]}"; do
    if [ "${ORDER[$i]}" == "${START}" ]; then
        START_INDEX=$i
        break
    fi
done
if [ "${START_INDEX}" -eq -1 ]; then
    echo "Unknown package '${START}'. Known packages, in build order: ${ORDER[*]}" >&2
    exit 1
fi

for i in "${!ORDER[@]}"; do
    if [ "$i" -lt "${START_INDEX}" ]; then
        continue
    fi
    pkg="${ORDER[$i]}"
    echo "=== Building ${pkg} ==="
    ./build-${pkg}.sh
done

./check-no-homebrew-links.sh
