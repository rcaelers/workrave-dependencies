#!/usr/bin/env bash -e

# Sanity check: nothing in _deploy/dependencies should link against Homebrew.
# Everything here is supposed to be self-contained (universal arm64+x86_64,
# buildable on a clean machine) — a build script that picks up a stray
# Homebrew lib (e.g. Boost.Locale/Regex auto-detecting a system ICU, or a
# CMake find_package() resolving something from /opt/homebrew instead of
# our own _deploy prefix) would silently break both properties at once.
#
# Checks every Mach-O dylib/executable under _deploy/dependencies for:
#   - LC_LOAD_DYLIB / LC_ID_DYLIB entries with an absolute Homebrew path
#   - LC_RPATH entries pointing into a Homebrew prefix (which would let an
#     @rpath-relative load resolve to Homebrew at runtime even though the
#     dependency itself doesn't name an absolute Homebrew path)
#
# Usage: ./check-no-homebrew-links.sh [dir]   (defaults to
# macos/_deploy/dependencies; pass an explicit dir to check the combined
# CI release artifact instead, e.g. combined-dependencies/). Exits non-zero
# and lists offenders if anything is found.

BASEDIR=$(cd "$(dirname "$0")" && pwd)
DEPLOYDIR="${1:-${BASEDIR}/_deploy/dependencies}"

if [ ! -d "${DEPLOYDIR}" ]; then
    echo "No ${DEPLOYDIR} — nothing to check." >&2
    exit 1
fi

BLOCKED='/opt/homebrew|/usr/local/Cellar|/usr/local/opt|/usr/local/lib|/usr/local/bin|/usr/local/share'

FOUND=0

while IFS= read -r -d '' f; do
    if ! file "$f" | grep -q "Mach-O"; then
        continue
    fi

    deps=$(otool -L "$f" 2>/dev/null | tail -n +2 | awk '{print $1}' | grep -E "${BLOCKED}" || true)
    if [ -n "${deps}" ]; then
        while IFS= read -r dep; do
            echo "!!! $f links against Homebrew: ${dep}" >&2
        done <<<"${deps}"
        FOUND=1
    fi

    rpaths=$(otool -l "$f" 2>/dev/null | awk '/LC_RPATH/{getline; getline; print $2}' | grep -E "${BLOCKED}" || true)
    if [ -n "${rpaths}" ]; then
        while IFS= read -r rp; do
            echo "!!! $f has an LC_RPATH into Homebrew: ${rp}" >&2
        done <<<"${rpaths}"
        FOUND=1
    fi
done < <(find "${DEPLOYDIR}" -type f \( -name "*.dylib" -o -perm -u+x \) -print0)

if [ "${FOUND}" -eq 1 ]; then
    echo "Homebrew linkage detected in ${DEPLOYDIR} — see above." >&2
    exit 1
fi

echo "OK: no Homebrew linkage found in ${DEPLOYDIR}."
