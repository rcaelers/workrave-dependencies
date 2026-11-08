"""macOS backend for the shared build.py entry point."""

import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

import macos_sdk

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "macos.lock"


def run(*args, env=None):
    subprocess.run(list(map(str, args)), check=True, env=env)


def profiles(arch):
    native = "arm64" if platform.machine() == "arm64" else "x86_64"
    return [f"-pr:b=macos-{native}", f"-pr:h=macos-{arch}"]


def check_graph(arch, output):
    run("conan", "graph", "info", ROOT, *profiles(arch), f"--lockfile={LOCK}",
        "--build=missing", "-c:a", "tools.graph:skip_binaries=False",
        "--format=json", f"--out-file={output}")
    graph = json.loads(output.read_text())["graph"]
    invalid = {n.get("ref"): n["info_invalid"] for n in graph["nodes"].values() if n.get("info_invalid")}
    if graph.get("error") or invalid:
        raise RuntimeError(f"Invalid macOS {arch} graph: {graph.get('error') or invalid}")


def smoke(source, output, jobs, *configuration, environment=None):
    run("cmake", "--fresh", "-S", source, "-B", output, "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release", *configuration, env=environment)
    run("cmake", "--build", output, "--parallel", jobs, env=environment)


def validate_sdk(sdk, jobs):
    """Use the SDK from a different path, without Conan's generated toolchain."""
    sdk = sdk.resolve()
    print(f"Checking universal SDK binaries: {sdk}", flush=True)
    for path in sdk.rglob("*"):
        if path.is_file() and not path.is_symlink() and macos_sdk.is_binary(path):
            if macos_sdk.architectures(path) != set(macos_sdk.ARCHES):
                raise RuntimeError(f"Non-universal SDK binary: {path}")
            macos_sdk.check_deployment_target(path, "14.4")
    # Rename, rather than copying a multi-GB SDK. Restoring is unconditional,
    # including after a failed configure/link or an interrupt.
    with tempfile.TemporaryDirectory(prefix="workrave-sdk-relocation-", dir=sdk.parent) as temporary:
        relocated = Path(temporary) / "SDK with spaces"
        sdk.rename(relocated)
        try:
            prefix = macos_sdk.run(relocated / "bin/qtpaths", "--query", "QT_INSTALL_PREFIX")
            if Path(prefix).resolve() != (relocated / "packages/qt").resolve():
                raise RuntimeError(f"qtpaths still refers to a different SDK: {prefix}")
            smoke(ROOT / "smoke", Path(temporary) / "smoke", jobs,
                  f"-DCMAKE_PREFIX_PATH={relocated}",
                  f"-DWORKRAVE_SMOKE_SDK_ROOT={relocated}",
                  '-DCMAKE_OSX_ARCHITECTURES=arm64;x86_64',
                  '-DCMAKE_OSX_DEPLOYMENT_TARGET=14.4', '-DWORKRAVE_SMOKE_GRPC=ON', '-DWORKRAVE_SMOKE_DBUS=ON',
                  '-DWORKRAVE_SMOKE_GTEST_ASAN=ON')
            print("Checking sanitizer-instrumented GoogleTest registration", flush=True)
            sanitizer_environment = dict(os.environ)
            sanitizer_environment["ASAN_OPTIONS"] = (
                sanitizer_environment.get("ASAN_OPTIONS", "") + ":detect_container_overflow=1")
            subprocess.run([str(Path(temporary) / "smoke/dependencies-gtest-asan"), "--gtest_color=no"],
                           check=True, env=sanitizer_environment, timeout=60)
            app = Path(temporary) / "smoke/dependencies-smoke.app"
            binary = app / "Contents/MacOS/dependencies-smoke"
            if macos_sdk.architectures(binary) != set(macos_sdk.ARCHES):
                raise RuntimeError("Relocated SDK smoke executable is not universal")
            macos_sdk.run("codesign", "--verify", "--deep", "--strict", relocated / "packages/qt/bin/qtpaths")
            print("Deploying and signing the universal smoke app", flush=True)
            deployment = subprocess.run(
                list(map(str, (relocated / "bin/macdeployqt", app, f"-qmldir={ROOT / 'smoke'}",
                               "-codesign=-", "-no-strip"))),
                check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            print(deployment.stdout, flush=True)
            deployment.check_returncode()
            if re.search(r"(?m)^\s*ERROR:", deployment.stdout):
                raise RuntimeError("macdeployqt reported deployment errors")
            for path in app.rglob("*"):
                if path.is_file() and not path.is_symlink() and macos_sdk.is_binary(path):
                    if macos_sdk.architectures(path) != set(macos_sdk.ARCHES):
                        raise RuntimeError(f"Non-universal deployed binary: {path}")
                    for line in macos_sdk.run("otool", "-L", path).splitlines():
                        match = re.match(r"\s+(.+?) \(compatibility version", line)
                        if match and not match[1].startswith(("@", "/System/Library/", "/usr/lib/")):
                            raise RuntimeError(f"External deployed dependency: {path}: {match[1]}")
            run("codesign", "--verify", "--deep", "--strict", app)
            run(ROOT / "scripts/check-no-homebrew-links.sh", app)
            # This loads the deployed Cocoa/QML plugins and creates the Quick
            # component without showing a window or entering an event loop.
            environment = dict(os.environ)
            for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML_IMPORT_PATH", "QML2_IMPORT_PATH",
                        "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
                environment.pop(key, None)
            offline = Path(temporary) / "SDK offline"
            relocated.rename(offline)
            try:
                print("Running the deployed app with the SDK unavailable", flush=True)
                subprocess.run([str(binary), "--self-test"], check=True, env=environment, timeout=60)
            finally:
                offline.rename(relocated)
        finally:
            relocated.rename(sdk)
    run(ROOT / "scripts/check-no-homebrew-links.sh", sdk)


def main(args, parser):
    if sys.platform != "darwin":
        parser.error("macOS dependency builds require a Mac with Xcode")
    os.environ.setdefault("CONAN_HOME", str(ROOT / "_build/conan-home-macos"))
    clang = subprocess.check_output(["/usr/bin/clang", "--version"], text=True)
    os.environ.setdefault("WORKRAVE_APPLE_CLANG", re.search(r"Apple clang version (\d+)", clang)[1])
    pkg_config = shutil.which("pkg-config")
    if pkg_config:
        os.environ.setdefault("WORKRAVE_PKG_CONFIG", pkg_config)
    if args.validate:
        validate_sdk(args.sdk_output, args.jobs)
        print(f"Validated universal macOS SDK: {args.sdk_output}")
        return
    if not args.check and not args.update_lock and args.arch == "all" and (args.sdk_output.exists() or args.sdk_output.is_symlink()):
        parser.error("SDK output already exists; choose another --sdk-output or use --validate")
    run(sys.executable, ROOT / "setup.py")
    if args.update_lock:
        # Capture native tools for both native builder architectures as well as
        # target packages, without updating a previously resolved reference.
        temporary = ROOT / "_build/macos.lock"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        first = True
        for builder in ("arm64", "x86_64"):
            for target in ("arm64", "x86_64"):
                run("conan", "lock", "create", ROOT, f"-pr:b=macos-{builder}", f"-pr:h=macos-{target}",
                    *( ["--lockfile="] if first else [f"--lockfile={temporary}", "--lockfile-partial"] ),
                    f"--lockfile-out={temporary}")
                first = False
        shutil.copy2(temporary, LOCK)
        return
    if not LOCK.exists():
        parser.error("Missing macos.lock; run --platform macos --update-lock first")
    for arch in ("arm64", "x86_64") if args.arch == "all" else (args.arch,):
        output = ROOT / "_build" / f"macos-{arch}"
        output.mkdir(parents=True, exist_ok=True)
        if args.check:
            check_graph(arch, output / "graph-check.json")
            continue
        run("conan", "install", ROOT, *profiles(arch), f"--lockfile={LOCK}", "--build=missing",
            f"-of={output}", "-c:a", f"tools.build:jobs={args.jobs}",
            "-c:a", "tools.graph:skip_binaries=False", "--format=json", f"--out-file={output / 'graph.json'}")
        graph = json.loads((output / "graph.json").read_text())["graph"]
        hosts = macos_sdk.host_packages(graph)
        run(ROOT / "scripts/check-no-homebrew-links.sh", hosts["qt"]["package_folder"])
        # Native package helpers use find_program; prioritize the resolved SDK
        # tools over unrelated Homebrew protoc/plugin versions. Cross-builds
        # import their native tools explicitly in conanfile.py instead.
        programs = ";".join(str(Path(hosts[name]["package_folder"]) / "bin")
                            for name in ("qt", "protobuf", "grpc"))
        smoke(ROOT / "smoke", output / "smoke", args.jobs,
              f"-DCMAKE_TOOLCHAIN_FILE={output / 'build/Release/generators/conan_toolchain.cmake'}",
              f"-DCMAKE_PROGRAM_PATH={programs}",
              '-DWORKRAVE_SMOKE_GRPC=ON', '-DWORKRAVE_SMOKE_DBUS=ON')
        if args.export_cache:
            run("conan", "list", f"--graph={output / 'graph.json'}", "--format=json",
                f"--out-file={output / 'packages.json'}")
            run("conan", "cache", "save", f"--list={output / 'packages.json'}", "--no-source",
                f"--file={output / 'conan-cache.tgz'}")
    if not args.check and args.arch == "all":
        macos_sdk.export(ROOT / "_build/macos-arm64", ROOT / "_build/macos-x86_64", args.sdk_output)
        validate_sdk(args.sdk_output, args.jobs)
        print(f"Built and checked universal macOS SDK: {args.sdk_output}")
