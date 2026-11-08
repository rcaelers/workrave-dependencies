#!/usr/bin/env bash -e

# Check a Conan package, universal SDK or deployed app for accidental Homebrew
# dependencies and search paths. This validates self-contained Conan artifacts.
# Usage: conan/scripts/check-no-homebrew-links.sh [directory]
# The default directory is conan/_build/macos-universal.

BASEDIR=$(cd "$(dirname "$0")" && pwd)
DEPLOYDIR="${1:-${BASEDIR}/../_build/macos-universal}"

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
