#!/usr/bin/env python3
"""Resolve, build and export the Qt dependency SDK using Conan 2."""

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "windows.lock"


def run(*arguments):
    subprocess.run([str(argument) for argument in arguments], check=True)


def symbol_helper():
    spec = importlib.util.spec_from_file_location(
        "workrave_symbols", ROOT / "config/extensions/hooks/hook_workrave_symbols.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def export_symbols(graph_file, output, arch):
    helper = symbol_helper()
    graph = json.loads(graph_file.read_text())["graph"]
    manifests = []
    with tarfile.open(output / "symbols.tar.gz", "w:gz") as archive:
        for node in graph["nodes"].values():
            if node.get("context") != "host" or not node.get("package_folder"):
                continue
            package = Path(node["package_folder"])
            manifest_path = package / "symbols/manifest.json"
            binaries = {
                p.relative_to(package).as_posix()
                for p in package.rglob("*")
                if p.is_file() and p.suffix.lower() in (".dll", ".exe")
            }
            if not binaries:
                continue
            if not manifest_path.exists():
                raise RuntimeError(f"Cached package has no symbols: {node['ref']}")
            manifest = json.loads(manifest_path.read_text())
            if binaries != {entry["binary"] for entry in manifest}:
                raise RuntimeError(f"Incomplete symbol manifest: {node['ref']}")
            # Check cached packages as well as newly built ones, without modifying the cache.
            for entry in manifest:
                machine, guid, age, _ = helper.pe_debug_info(package / entry["binary"])
                if machine != {"x86_64": 0x8664, "arm64": 0xAA64}[arch]:
                    raise RuntimeError(f"Wrong architecture: {entry['binary']}")
                if helper.pdb_identity(package / entry["pdb"]) != (guid, age):
                    raise RuntimeError(f"Mismatched PDB: {entry['binary']}")
                if (
                    hashlib.sha256((package / entry["binary"]).read_bytes()).hexdigest()
                    != entry["sha256"]
                ):
                    raise RuntimeError(
                        f"Binary changed after packaging: {entry['binary']}"
                    )
            prefix = f"{node['name']}-{node['version']}/{node['package_id']}"
            archive.add(package / "symbols", arcname=prefix)
            manifests.append(
                {
                    "ref": node["ref"],
                    "package_id": node["package_id"],
                    "package_revision": node["prev"],
                    "modules": manifest,
                }
            )
    (output / "symbols.json").write_text(json.dumps(manifests, indent=2) + "\n")


def build(arch, jobs, export):
    output = ROOT / "_build" / f"windows-{arch}"
    output.mkdir(parents=True, exist_ok=True)
    graph = output / "graph.json"
    # Conan list omits skipped transitive binaries. Include them in portable
    # caches so compatible dependency selections (and Qt package IDs) survive
    # restoration into a fresh cache.
    export_config = ["-c:a", "tools.graph:skip_binaries=False"] if export else []
    run(
        "conan",
        "install",
        ROOT,
        "-pr:b=linux-x86_64",
        f"-pr:h=windows-{arch}",
        f"--lockfile={LOCK}",
        "--build=missing",
        f"-of={output}",
        "-c:a",
        f"tools.build:jobs={jobs}",
        *export_config,
        "--format=json",
        f"--out-file={graph}",
    )
    generators = output / "build/RelWithDebInfo/generators"
    run(
        "cmake",
        # The previous Conan volume may be gone; discard cached package paths.
        "--fresh",
        "-S",
        ROOT / "smoke",
        "-B",
        output / "smoke",
        "-G",
        "Ninja",
        f"-DCMAKE_TOOLCHAIN_FILE={generators / 'conan_toolchain.cmake'}",
        "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
        "-DWORKRAVE_SMOKE_GRPC=ON",
    )
    run("cmake", "--build", output / "smoke", "--parallel", jobs)
    probe = output / "smoke/package"
    run("cmake", "--install", output / "smoke", "--prefix", probe)
    validate(arch)
    # Keep the toolchain's runtime DLLs with the SDK. Upstream does not ship PDBs
    # for these; see README. Do not mix in MSYS2 or GCC MinGW runtime libraries.
    target = "aarch64" if arch == "arm64" else "x86_64"
    runtime = (
        Path(os.environ.get("LLVM_MINGW_ROOT", "/opt/llvm-mingw"))
        / f"{target}-w64-mingw32/bin"
    )
    destination = output / "runtime"
    destination.mkdir(exist_ok=True)
    for name in ("libc++.dll", "libunwind.dll", "libwinpthread-1.dll"):
        shutil.copy2(runtime / name, destination / name)
    shutil.copy2(runtime.parent.parent / "LICENSE.TXT", destination / "LICENSE.TXT")
    shutil.copy2(LOCK, output / LOCK.name)
    if export:
        packages = output / "packages.json"
        run(
            "conan",
            "list",
            f"--graph={graph}",
            "--format=json",
            f"--out-file={packages}",
        )
        run(
            "conan",
            "cache",
            "save",
            f"--list={packages}",
            "--no-source",
            f"--file={output / 'conan-cache.tgz'}",
        )
    print(f"Built and checked Windows {arch}: {output}")


def validate(arch):
    """Validate the existing smoke build and all resolved package binaries/PDBs."""
    output = ROOT / "_build" / f"windows-{arch}"
    for name in ("dependencies-smoke", "dependencies-grpc-af-unix"):
        if not (output / f"smoke/package/bin/{name}.exe").is_file():
            raise RuntimeError(f"Missing {name}.exe; compile and install the smoke build before validation")
    symbol_helper().retain_symbols(
        output / "smoke/package", output / "smoke", "armv8" if arch == "arm64" else arch
    )
    export_symbols(output / "graph.json", output, arch)
    print(f"Validated Windows {arch} smoke build and dependency symbols")


def check_graph(arch):
    output = ROOT / "_build" / f"windows-{arch}" / "graph-check.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        "conan",
        "graph",
        "info",
        ROOT,
        "-pr:b=linux-x86_64",
        f"-pr:h=windows-{arch}",
        f"--lockfile={LOCK}",
        "--format=json",
        f"--out-file={output}",
    )
    graph = json.loads(output.read_text())["graph"]
    invalid = {
        node.get("ref"): node["info_invalid"]
        for node in graph["nodes"].values()
        if node.get("info_invalid")
    }
    # graph info can exit successfully even with invalid package configurations.
    # Missing binaries are expected on a fresh cache; invalid recipes are not.
    if graph.get("error") or invalid:
        raise RuntimeError(
            f"Invalid Windows {arch} graph: {graph.get('error') or invalid}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("windows", "macos"),
                        default="macos" if sys.platform == "darwin" else "windows")
    parser.add_argument("--sdk-output", type=Path, default=ROOT / "_build/macos-universal",
                        help="Destination for the universal macOS SDK (must not exist)")
    parser.add_argument("--arch", choices=("x86_64", "arm64", "all"), default="all")
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 2, 8))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--update-lock",
        action="store_true",
        help="Resolve both graphs, write the lockfile, then exit",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Validate locked graphs without building packages",
    )
    mode.add_argument(
        "--validate",
        action="store_true",
        help="Validate an existing Windows build/PDBs or exported macOS SDK",
    )
    parser.add_argument(
        "--export-cache",
        action="store_true",
        help="Also create a portable Conan cache archive",
    )
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.platform == "macos":
        from build_macos import main as macos_main
        macos_main(args, parser)
        return
    if sys.platform != "linux" or not shutil.which("x86_64-w64-mingw32-clang"):
        parser.error("Run this command in the llvm-mingw build image")
    if args.validate:
        for arch in ("x86_64", "arm64") if args.arch == "all" else (args.arch,):
            validate(arch)
        return
    run(sys.executable, ROOT / "setup.py")
    if args.update_lock:
        # A lock contains references, not architecture settings. Extend the x64
        # graph with anything needed only by ARM64, preserving shared versions.
        temporary = ROOT / "_build/windows.lock"
        temporary.parent.mkdir(exist_ok=True)
        run(
            "conan",
            "lock",
            "create",
            ROOT,
            "-pr:b=linux-x86_64",
            "-pr:h=windows-x86_64",
            f"--lockfile-out={temporary}",
        )
        run(
            "conan",
            "lock",
            "create",
            ROOT,
            "-pr:b=linux-x86_64",
            "-pr:h=windows-arm64",
            f"--lockfile={temporary}",
            "--lockfile-partial",
            f"--lockfile-out={LOCK}",
        )
        return
    if not LOCK.exists():
        parser.error("Missing windows.lock; run --update-lock first")
    for arch in ("x86_64", "arm64") if args.arch == "all" else (args.arch,):
        if args.check:
            check_graph(arch)
        else:
            build(arch, args.jobs, args.export_cache)


if __name__ == "__main__":
    main()
