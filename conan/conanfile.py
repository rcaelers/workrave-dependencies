from pathlib import Path
from typing import ClassVar

from conan import ConanFile
from conan.tools.build import cross_building
from conan.tools.cmake import CMakeDeps, CMakeToolchain, cmake_layout


class WorkraveDependencies(ConanFile):
    settings = "os", "arch", "compiler", "build_type"
    default_options: ClassVar[dict[str, bool]] = {
        "qt/*:shared": True,
        "fmt/*:shared": True,
        "spdlog/*:shared": True,
        "boost/*:shared": True,
        "openssl/*:shared": True,
        "sqlite3/*:shared": True,
        "sqlite3/*:enable_column_metadata": True,
    }

    def requirements(self):
        self.requires("qt/6.11.1")
        self.requires("boost/1.91.0")
        self.requires("openssl/3.6.4")
        # spdlog 1.17's recipe pins fmt 12.1; use the compatible 12.2 update.
        self.requires("fmt/12.2.0", force=True)
        self.requires("spdlog/1.17.0")
        self.requires("sqlite3/3.53.4")
        self.requires("gtest/1.18.0")
        self.requires("zlib/1.3.2")  # Crashpad links zlib directly.
        self.requires("libxml2/2.15.4")  # Unfold parses XML appcasts.

    def layout(self):
        cmake_layout(self)

    def build_requirements(self):
        if cross_building(self):
            self.tool_requires("qt/6.11.1")

    def generate(self):
        CMakeDeps(self).generate()
        toolchain = CMakeToolchain(self)
        toolchain.user_presets_path = False
        if cross_building(self):
            qt_host = Path(self.dependencies.direct_build["qt"].package_folder)
            toolchain.variables["QT_HOST_PATH"] = qt_host.as_posix()
            # Import Linux moc/rcc/QML tools before the target recipe's helpers.
            toolchain.variables["CMAKE_PROJECT_INCLUDE"] = (
                qt_host / "lib/cmake/Qt6Core/conan_qt_executables_variables.cmake"
            ).as_posix()
        toolchain.generate()
