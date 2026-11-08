"""Native integration tests: real Mach-O slices, CMakeDeps and cache removal."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("macos_sdk", ROOT / "macos_sdk.py")
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("conan"), "needs macOS, Xcode and Conan")
class UniversalSDKTest(unittest.TestCase):
    def command(self, *args):
        result = subprocess.run(list(map(str, args)), env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode:
            self.fail(f"{' '.join(map(str, args))}\n{result.stdout}")
        return result.stdout

    def test_relocated_cmakedeps_without_original_cache(self):
        with tempfile.TemporaryDirectory(prefix="workrave-universal-test-") as temporary:
            base = Path(temporary)
            self.env = dict(os.environ, CONAN_HOME=str(base / "cache"))
            recipe = base / "recipe"
            recipe.mkdir()
            (recipe / "conanfile.py").write_text('''
import os
from conan import ConanFile
from conan.tools.files import copy
class Probe(ConanFile):
    name = "qt"
    version = "0.0"
    settings = "os", "arch", "compiler", "build_type"
    package_type = "shared-library"
    def package(self):
        copy(self, "*", src=os.path.join(self.source_folder, "artifacts", str(self.settings.arch)), dst=self.package_folder)
    def package_info(self):
        self.cpp_info.set_property("cmake_file_name", "Qt6")
        self.cpp_info.components["probe"].libs = ["SdkProbe"]
        self.cpp_info.components["probe"].set_property("cmake_target_name", "Qt6::Probe")
''')
            (recipe / "probe.c").write_text('int sdk_probe(void) { return 42; }\n')
            (recipe / "tool.c").write_text('int sdk_probe(void); int main(void) { return sdk_probe() != 42; }\n')
            consumer = base / "consumer"
            consumer.mkdir()
            (consumer / "conanfile.py").write_text(f'''
import importlib.util
from conan import ConanFile
from conan.tools.cmake import cmake_layout
spec = importlib.util.spec_from_file_location("workrave_consumer", {str(ROOT / "conanfile.py")!r})
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
class Consumer(ConanFile):
    settings = "os", "arch", "compiler", "build_type"
    requires = "qt/0.0"
    def generate(self):
        shared.WorkraveDependencies.generate(self)
    def layout(self):
        cmake_layout(self)
''')
            builds = []
            for arch, setting in (("arm64", "armv8"), ("x86_64", "x86_64")):
                artifacts = recipe / "artifacts" / setting
                for directory in ("lib", "include", "bin"):
                    (artifacts / directory).mkdir(parents=True)
                (artifacts / "modules").mkdir()
                (artifacts / "modules/Probe.json").write_text(json.dumps({
                    "schema_version": 3, "name": "Probe", "bundle_type": "framework",
                    "platforms": [{"name": "Darwin", "version": "27.2" if arch == "arm64" else "20",
                                   "targets": [{"architecture": arch}]}],
                }))
                cmake = artifacts / "lib/cmake/Qt6Probe"
                cmake.mkdir(parents=True)
                features = "shared;neon" if arch == "arm64" else "shared;sse2;qml_jit"
                disabled = "sse2;qml_jit" if arch == "arm64" else "neon"
                (cmake / "Qt6ProbeTargets.cmake").write_text(
                    f'set_target_properties(Qt6::Probe PROPERTIES\n'
                    f'  QT_ENABLED_PRIVATE_FEATURES "{features}"\n'
                    f'  QT_DISABLED_PRIVATE_FEATURES "{disabled}"\n'
                    f'  _qt_sbom_spdx_id "thin-{arch}"\n)\n')
                if arch == "x86_64":
                    jit = artifacts / "include/QtQml/0.0/QtQml/private/qv4baselinejit_p.h"
                    jit.parent.mkdir(parents=True)
                    jit.write_text('#define SDK_PROBE_INTEL_JIT 1\n')
                (artifacts / "sbom").mkdir()
                (artifacts / "sbom/probe.spdx").write_text(f"Original {arch} inventory\n")
                script = artifacts / "bin/xml2-config"
                script.write_text(f'#!/bin/sh\nprefix=/original/{arch}\necho "$prefix"\n')
                script.chmod(0o755)
                script = artifacts / "bin/qt-cmake"
                script.write_text('#!/bin/sh\nscript_dir_path=`dirname $0`\n'
                                  'script_dir_path=`(cd "$script_dir_path"; pwd)`\n'
                                  'original_cmake_path="/original/cache/cmake"\n'
                                  'echo "$script_dir_path"\n')
                script.chmod(0o755)
                (artifacts / "mkspecs").mkdir()
                enabled, disabled = ("neon", "sse2") if arch == "arm64" else ("sse2", "neon")
                (artifacts / "mkspecs/qmodule.pri").write_text(
                    f'QT_CPU_FEATURES.{arch} = {enabled}\n'
                    f'QT.global_private.enabled_features = shared {enabled}\n'
                    f'QT.global_private.disabled_features = {disabled}\n'
                    f'CONFIG += shared {enabled}\nQT_COORD_TYPE = double\n')
                cross = "cross_compile " if arch == "x86_64" else ""
                disabled_cross = "cross_compile " if arch == "arm64" else ""
                (artifacts / "mkspecs/qconfig.pri").write_text(
                    f'QT_ARCH = {arch}\nQT_BUILDABI = \nQT_LIBCPP_ABI_TAG = \nQT_ARCHS = {arch}\n'
                    f'QT.global.enabled_features = {cross}shared\n'
                    f'QT.global.disabled_features = {disabled_cross}static\n'
                    f'QT_CONFIG += {cross}shared\nCONFIG += {cross}shared\n')
                if arch == "x86_64":
                    qmodule = artifacts / "mkspecs/qmodule.pri"
                    qmodule.write_text(qmodule.read_text().replace(
                        'QT_CPU_FEATURES.x86_64 = sse2\n',
                        'host_build {\n    QT_CPU_FEATURES.arm64 = neon\n} else {\n'
                        '    QT_CPU_FEATURES.x86_64 = sse2\n}\n'))
                    qconfig = artifacts / "mkspecs/qconfig.pri"
                    qconfig.write_text(qconfig.read_text().replace(
                        'QT_ARCH = x86_64\nQT_BUILDABI = \nQT_LIBCPP_ABI_TAG = \n',
                        'host_build {\n    QT_ARCH = arm64\n    QT_BUILDABI = \n'
                        '    QT_TARGET_ARCH = x86_64\n    QT_TARGET_BUILDABI = \n} else {\n'
                        '    QT_ARCH = x86_64\n    QT_BUILDABI = \n    QT_LIBCPP_ABI_TAG = \n}\n'))
                script = artifacts / "bin/c_rehash"
                script.write_text(f'#!perl\nmy $dir = "/original/{arch}/res";\nmy $prefix = "/";\nprint "$dir\\n";\n')
                script.chmod(0o755)
                library = artifacts / "lib/libSdkProbe.1.2.dylib"
                self.command("/usr/bin/clang", "-arch", arch, "-mmacosx-version-min=14.4",
                             "-dynamiclib", recipe / "probe.c", "-o", library,
                             "-Wl,-headerpad_max_install_names", f"-Wl,-rpath,/original/{arch}",
                             "-install_name", "@rpath/libSdkProbe.1.dylib")
                (artifacts / "lib/libSdkProbe.1.dylib").symlink_to(library.name)
                (artifacts / "lib/libSdkProbe.dylib").symlink_to("libSdkProbe.1.dylib")
                self.command("/usr/bin/clang", "-arch", arch, "-mmacosx-version-min=14.4",
                             "-c", recipe / "probe.c", "-o", base / f"{arch}.o")
                self.command("/usr/bin/ar", "rcs", artifacts / "lib/libSdkStaticProbe.a", base / f"{arch}.o")
                self.command("/usr/bin/clang", "-arch", arch, "-mmacosx-version-min=14.4",
                             recipe / "tool.c", library, "-Wl,-headerpad_max_install_names",
                             f"-Wl,-rpath,/original/{arch}", "-Wl,-rpath,@loader_path/../lib",
                             "-o", artifacts / "bin/sdk-probe")
                (artifacts / "include/probe.h").write_text(
                    f'#define SDK_PROBE_ARCH_{arch} 1\nint sdk_probe(void);\n' +
                    ('#include "QtQml/0.0/QtQml/private/qv4baselinejit_p.h"\n' if arch == 'x86_64' else ''))
                profile = base / f"{arch}.profile"
                profile.write_text(f'''[settings]
os=Macos
os.version=14.4
arch={setting}
compiler=apple-clang
compiler.version=21
compiler.libcxx=libc++
compiler.cppstd=20
build_type=Release
''')
                self.command("conan", "export-pkg", recipe, f"-pr:h={profile}", f"-pr:b={profile}", "-nr")
                build = base / arch
                self.command("conan", "install", consumer, f"-pr:h={profile}", f"-pr:b={profile}",
                             f"-of={build}", "-nr", "--format=json", f"--out-file={build / 'graph.json'}")
                builds.append(build)
            original = base / "original SDK"
            sdk.export(*builds, original)
            relocated = base / "moved SDK"
            original.rename(relocated)
            shutil.rmtree(base / "cache")
            shutil.rmtree(recipe)
            library = relocated / "packages/qt/lib/libSdkProbe.1.2.dylib"
            self.assertEqual(sdk.architectures(library), set(sdk.ARCHES))
            identities = self.command("otool", "-D", library)
            self.assertIn('@rpath/libSdkProbe.1.dylib', identities)
            self.assertNotIn('@rpath/libSdkProbe.1.2.dylib', identities)
            self.assertEqual(sdk.architectures(relocated / "packages/qt/lib/libSdkStaticProbe.a"), set(sdk.ARCHES))
            module = json.loads((relocated / "packages/qt/modules/Probe.json").read_text())
            self.assertEqual({t["architecture"] for p in module["platforms"] for t in p["targets"]}, set(sdk.ARCHES))
            self.assertEqual(module["bundle_type"], "none")
            for arch in sdk.ARCHES:
                self.assertEqual((relocated / f"packages/qt/sbom/{arch}/probe.spdx").read_text(),
                                 f"Original {arch} inventory\n")
            self.assertFalse((relocated / "packages/qt/sbom/probe.spdx").exists())
            features = (relocated / "packages/qt/lib/cmake/Qt6Probe/Qt6ProbeTargets.cmake").read_text()
            self.assertIn('QT_ENABLED_PRIVATE_FEATURES "shared"', features)
            self.assertIn('QT_DISABLED_PRIVATE_FEATURES "sse2;qml_jit;neon"', features)
            self.assertNotIn('_qt_sbom_', features)
            self.assertIn('QT.global_private.enabled_features = shared\n',
                          (relocated / "mkspecs/qmodule.pri").read_text())
            self.command(relocated / "bin/sdk-probe")
            self.assertEqual(Path(self.command(relocated / "bin/qt-cmake").strip()).resolve(),
                             (relocated / "packages/qt/bin").resolve())
            self.assertNotIn('/original/cache', (relocated / "bin/qt-cmake").read_text())
            self.assertEqual(Path(self.command(relocated / "bin/xml2-config").strip()).resolve(),
                             (relocated / "packages/qt").resolve())
            self.assertEqual(Path(self.command(relocated / "bin/c_rehash").strip()).resolve(),
                             (relocated / "packages/qt/res").resolve())
            self.command("codesign", "--verify", "--strict", relocated / "bin/sdk-probe")
            source = base / "app"
            source.mkdir()
            (source / "main.c").write_text('''#include <probe.h>
#if defined(__arm64__) && !defined(SDK_PROBE_ARCH_arm64)
#error wrong header
#endif
#if defined(__x86_64__) && !defined(SDK_PROBE_ARCH_x86_64)
#error wrong header
#endif
int main(void) { return sdk_probe() != 42; }
''')
            (source / "CMakeLists.txt").write_text('''cmake_minimum_required(VERSION 3.21)
project(SDKConsumer C)
# Exercise the same prefix search used by built-in Find modules, before any
# generated package config can change the search policy.
find_path(SDK_PROBE_INCLUDE probe.h REQUIRED)
find_library(SDK_PROBE_LIBRARY SdkProbe REQUIRED)
find_package(Qt6Probe 0.0 CONFIG REQUIRED)
get_target_property(probe_includes Qt6::Probe INTERFACE_INCLUDE_DIRECTORIES)
include(CheckCSourceCompiles)
set(CMAKE_REQUIRED_INCLUDES "${probe_includes}")
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
check_c_source_compiles("#include <probe.h>\nint main(void) { return 0; }" SDK_PROBE_HEADERS_FOUND)
if(NOT SDK_PROBE_HEADERS_FOUND)
  message(FATAL_ERROR "Imported include directories must work in configure-time header probes")
endif()
find_package(Qt6CorePrivate CONFIG QUIET)
if(Qt6CorePrivate_FOUND)
  message(FATAL_ERROR "An absent module must not be advertised as available")
endif()
add_executable(probe main.c)
target_link_libraries(probe PRIVATE Qt6::Probe)
''')
            self.command("cmake", "-S", source, "-B", base / "app-build", "-G", "Ninja",
                         "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_PREFIX_PATH={relocated}",
                         "-DCMAKE_OSX_ARCHITECTURES=arm64;x86_64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=14.4")
            self.command("cmake", "--build", base / "app-build")
            self.assertEqual(sdk.architectures(base / "app-build/probe"), set(sdk.ARCHES))
            self.command(base / "app-build/probe")
            dependencies = self.command("otool", "-L", base / "app-build/probe")
            self.assertIn('@rpath/libSdkProbe.1.dylib', dependencies)
            self.assertNotIn('@rpath/libSdkProbe.1.2.dylib', dependencies)
            for path in relocated.rglob("*.cmake"):
                self.assertNotIn(str(base / "cache"), path.read_text())

    def test_failed_export_leaves_no_partial_sdk(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            builds = []
            for name in ("arm", "intel"):
                build = base / name
                build.mkdir()
                (build / "graph.json").write_text(json.dumps({"graph": {"nodes": {
                    "1": {"context": "host", "ref": "qt/0.0", "name": "qt"},
                }}}))
                builds.append(build)
            with self.assertRaisesRegex(RuntimeError, "Missing exported package"):
                sdk.export(*builds, base / "sdk")
            self.assertFalse((base / "sdk").exists())

    def test_rejects_different_resources_and_missing_slices(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            left, right = base / "left.json", base / "right.json"
            left.write_text('{"value": 1}')
            right.write_text('{"value": 2}')
            with self.assertRaisesRegex(RuntimeError, "explicit handling"):
                sdk.merge_file(left, right, base / "out.json", ({}, {}), {})
            source = base / "probe.c"
            source.write_text('int test(void) { return 0; }')
            self.env = dict(os.environ)
            self.command("/usr/bin/clang", "-arch", "arm64", "-c", source, "-o", base / "thin.o")
            with self.assertRaisesRegex(RuntimeError, "expected x86_64"):
                sdk.merge_file(base / "thin.o", base / "thin.o", base / "out.o", ({}, {}), {"binaries": 0})
            self.command("/usr/bin/clang", "-arch", "arm64", "-mmacosx-version-min=15.0",
                         "-dynamiclib", source, "-o", base / "newer.dylib")
            with self.assertRaisesRegex(RuntimeError, "Wrong macOS deployment target"):
                sdk.check_deployment_target(base / "newer.dylib", "14.4")


if __name__ == "__main__":
    unittest.main()
