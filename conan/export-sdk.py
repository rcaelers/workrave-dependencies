#!/usr/bin/env python3
"""Export resolved Conan packages as a relocatable Windows or universal macOS SDK.

Building, validation, archive caching and transfer belong to the caller.
See README.md for each platform's build and validation workflow.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def export(build, destination, key):
    graph = json.loads((build / "graph.json").read_text())["graph"]["nodes"]
    nodes = [
        node for node in graph.values()
        if node.get("context") == "host" and node.get("package_folder")
    ]
    mappings = {n["package_folder"]: f"@WORKRAVE_SDK_ROOT@/packages/{n['name']}" for n in nodes}
    for n in graph.values():
        if n.get("context") == "build" and n.get("name") == "qt" and n.get("package_folder"):
            mappings[n["package_folder"]] = "@WORKRAVE_SDK_ROOT@/packages/qt"

    packages = []
    for node in nodes:
        target = destination / "packages" / node["name"]
        shutil.copytree(node["package_folder"], target, symlinks=False)
        packages.append({
            key: node.get(key)
            for key in ("name", "version", "ref", "package_id", "prev", "license", "homepage", "description")
        })
    generators = destination / "generators"
    generators.mkdir()
    for path in (build / "build/RelWithDebInfo/generators").glob("*.cmake"):
        # Build-host launchers point at Linux tools; native Windows consumers
        # use the executables exported by each target package instead.
        if path.name in ("conan_toolchain.cmake", "conanbuildinfo.cmake", "workrave-host-tools.cmake"):
            continue
        shutil.copy2(path, generators / path.name)
    for path in destination.rglob("*"):
        if path.is_file() and path.suffix in (".cmake", ".pc", ".prl"):
            content = path.read_text()
            for old, new in sorted(mappings.items(), key=lambda item: -len(item[0])):
                content = content.replace(old, new)
            # Qt records the build tools and toolchain used when its package was
            # produced. They may belong to earlier cached Linux Qt builds; use
            # this SDK's native Windows tools/toolchain instead.
            if path.name == "Qt6Dependencies.cmake":
                content = re.sub(
                    r"/cache/conan/p/b/qt[^/]+/p",
                    "@WORKRAVE_SDK_ROOT@/packages/qt", content,
                )
            elif path.name == "qt.toolchain.cmake":
                content = re.sub(
                    r"set\(__qt_initially_configured_toolchain_file [^\n]+",
                    'set(__qt_initially_configured_toolchain_file "@WORKRAVE_SDK_ROOT@/toolchain.cmake")',
                    content,
                )
            path.write_text(content)

    # Cross-built Qt omits windeployqt. Export its matching source so Windows
    # can compile it once when initializing the SDK volume.
    qt = next(node for node in nodes if node["name"] == "qt")
    source = Path(output("conan", "cache", "path", qt["ref"], "--folder=source"))
    tool = destination / "src/windeployqt"
    shutil.copytree(source / "src/qtbase/src/tools/windeployqt", tool)
    shutil.copy2(ROOT / "sdk/windeployqt.cmake", tool / "CMakeLists.txt")
    shutil.copy2(ROOT / "sdk/toolchain.cmake", destination / "toolchain.cmake")

    compiler_root = Path(os.environ.get("LLVM_MINGW_ROOT", "/opt/llvm-mingw"))
    runtime = destination / "runtime"
    runtime.mkdir()
    for name in ("libc++.dll", "libunwind.dll", "libwinpthread-1.dll"):
        shutil.copy2(compiler_root / "x86_64-w64-mingw32/bin" / name, runtime)
    shutil.copy2(compiler_root / "LICENSE.TXT", runtime)
    shutil.copy2(ROOT / "windows.lock", destination)
    release = re.search(
        r"user.workrave:toolchain=llvm-mingw-([0-9]+)",
        (ROOT / "config/profiles/windows-llvm-mingw").read_text(),
    ).group(1)
    manifest = {
        "schema": 1,
        "cache_key": key,
        "architecture": "x86_64",
        "compiler": output("x86_64-w64-mingw32-clang", "--version"),
        "packages": packages,
        "llvm_mingw_release": release,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("windows", "macos"), default="windows")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "_build/windows-x86_64")
    parser.add_argument("--arm-build-dir", type=Path, default=ROOT / "_build/macos-arm64")
    parser.add_argument("--intel-build-dir", type=Path, default=ROOT / "_build/macos-x86_64")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-key")
    args = parser.parse_args()
    if args.platform == "macos":
        from macos_sdk import export as export_macos
        export_macos(args.arm_build_dir, args.intel_build_dir, args.output)
        print(f"Exported universal macOS SDK: {args.output}")
        return
    if not args.cache_key:
        parser.error("--cache-key is required for Windows SDK export")
    # Refuse to overlay an earlier SDK: removed dependencies must not linger.
    args.output.mkdir(parents=True, exist_ok=False)
    export(args.build_dir, args.output, args.cache_key)
    print(f"Exported Windows x86_64 SDK: {args.output}")


if __name__ == "__main__":
    main()
