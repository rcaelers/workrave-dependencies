from pathlib import Path
import re
import shlex
from typing import ClassVar

from conan import ConanFile
from conan.tools.build import cross_building
from conan.tools.cmake import CMakeDeps, CMakeToolchain, cmake_layout


class WorkraveDependencies(ConanFile):
    settings = "os", "arch", "compiler", "build_type"
    options = {"with_grpc": [True, False]}
    default_options: ClassVar[dict[str, bool]] = {
        "with_grpc": False,
        "qt/*:shared": True,
        "fmt/*:shared": True,
        "spdlog/*:shared": True,
        "boost/*:shared": True,
        "openssl/*:shared": True,
        "sqlite3/*:shared": True,
        "sqlite3/*:enable_column_metadata": True,
    }

    def requirements(self):
        self.requires("qt/6.12.0")
        self.requires("boost/1.91.0")
        # gRPC currently requires OpenSSL < 4; use the newest compatible 3.x.
        self.requires("openssl/3.6.5")
        # spdlog 1.17's recipe pins fmt 12.1; use the compatible 12.2 update.
        self.requires("fmt/12.2.0", force=True)
        self.requires("spdlog/1.17.0")
        self.requires("sqlite3/3.54.1")
        self.requires("gtest/1.18.0")
        self.requires("zlib/1.3.2")  # Crashpad links zlib directly.
        self.requires("libxml2/2.15.4")  # Unfold parses XML appcasts.
        if self.options.with_grpc:
            self.requires("grpc/1.84.0")
            self.requires("protobuf/6.33.5")

    def layout(self):
        cmake_layout(self)

    def build_requirements(self):
        if cross_building(self):
            self.tool_requires("qt/6.12.0")
            if self.options.with_grpc:
                self.tool_requires("grpc/1.84.0")
                self.tool_requires("protobuf/6.33.5")

    def generate(self):
        CMakeDeps(self).generate()
        # Workrave also calls find_package(Qt6DBus), rather than only asking
        # for a component of Qt6. CCI removes the native per-module configs;
        # provide compatible entry points backed by its generated targets.
        generators = Path(self.generators_folder)
        # These profiles generate one configuration per directory. Expose its
        # header paths without a configuration guard: Workrave also inspects
        # them in nested try_compile probes with no build type selected.
        for cmake in generators.glob("*.cmake"):
            text = cmake.read_text()
            rewritten = re.sub(r'\$<\$<CONFIG:[^>]+>:(\$\{[^}]+_INCLUDE_DIRS_[A-Z]+\})>', r'\1', text)
            if rewritten != text:
                cmake.write_text(rewritten)
        template = (Path(__file__).parent / "sdk/qt-module-config.cmake.in").read_text()
        modules = {"CorePrivate", "GuiPrivate", "WidgetsPrivate", "QmlPrivate", "QuickPrivate"}
        for component in self.dependencies["qt"].cpp_info.components.values():
            target = component.get_property("cmake_target_name")
            if target and target.startswith("Qt6::"):
                modules.add(target.removeprefix("Qt6::"))
        version = (generators / "Qt6ConfigVersion.cmake").read_text()
        for module in sorted(modules):
            (generators / f"Qt6{module}Config.cmake").write_text(template.replace("@MODULE@", module))
            (generators / f"Qt6{module}ConfigVersion.cmake").write_text(version)
        toolchain = CMakeToolchain(self)
        toolchain.user_presets_path = False
        contents = ""
        if cross_building(self):
            qt_host = Path(self.dependencies.direct_build["qt"].package_folder)
            toolchain.variables["QT_HOST_PATH"] = qt_host.as_posix()
            # Import native tools before the target packages' CMake helpers.
            contents = 'include("' + (
                qt_host / "lib/cmake/Qt6Core/conan_qt_executables_variables.cmake"
            ).as_posix() + '")\n'
        if self.options.get_safe("with_grpc", False):
            libraries = []
            if self.settings_build.os == "Macos":
                for collection in (self.dependencies.build, self.dependencies.host):
                    for _, dependency in collection.items():
                        if (dependency.settings.get_safe("os") == "Macos" and
                                dependency.settings.get_safe("arch", self.settings_build.arch) == self.settings_build.arch):
                            libraries.extend(dependency.cpp_info.libdirs)
            for package, name, target in (("protobuf", "protoc", "protobuf::protoc"),
                                          ("grpc", "grpc_cpp_plugin", "gRPC::grpc_cpp_plugin")):
                dependencies = self.dependencies.direct_build if cross_building(self) else self.dependencies.host
                executable = Path(dependencies[package].package_folder) / "bin" / name
                if self.settings_build.os == "Macos":
                    # /bin/sh strips inherited DYLD_* under SIP. Set the
                    # native package environment *after* that protected shell
                    # starts, before exec'ing protoc or its plugin. The SDK
                    # export fixes rpaths instead and needs no such wrappers.
                    wrapper = generators / f"workrave-{name}"
                    wrapper.write_text('#!/bin/sh\nexport DYLD_LIBRARY_PATH=' +
                                       shlex.quote(":".join(dict.fromkeys(libraries))) + '\nexec ' +
                                       shlex.quote(str(executable)) + ' "$@"\n')
                    wrapper.chmod(0o755)
                    executable = wrapper
                contents += (f'if(NOT TARGET {target})\n'
                             f'  add_executable({target} IMPORTED)\n'
                             f'  set_property(TARGET {target} PROPERTY IMPORTED_LOCATION "{executable.as_posix()}")\n'
                             'endif()\n')
        if contents:
            native_tools = generators / "workrave-host-tools.cmake"
            native_tools.write_text(contents)
            toolchain.variables["CMAKE_PROJECT_INCLUDE"] = native_tools.as_posix()
        toolchain.generate()
