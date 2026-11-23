"""Keep updater libraries and native generators available without gRPC."""

import importlib.util
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch


RECIPE = Path(__file__).resolve().parents[1] / "conanfile.py"


class UpdaterGraphTest(unittest.TestCase):
    def setUp(self):
        conan = ModuleType("conan")
        conan.ConanFile = object
        build = ModuleType("conan.tools.build")
        build.cross_building = lambda recipe: recipe.cross
        cmake = ModuleType("conan.tools.cmake")

        class CMakeDeps:
            def __init__(self, recipe):
                self.recipe = recipe

            def generate(self):
                (Path(self.recipe.generators_folder) / "Qt6ConfigVersion.cmake").write_text("")

        class CMakeToolchain:
            def __init__(self, recipe):
                self.variables = {}
                recipe.generated_toolchain = self

            def generate(self):
                pass

        cmake.CMakeDeps = CMakeDeps
        cmake.CMakeToolchain = CMakeToolchain
        cmake.cmake_layout = lambda recipe: None
        modules = {"conan": conan, "conan.tools": ModuleType("conan.tools"),
                   "conan.tools.build": build, "conan.tools.cmake": cmake}
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("updater_recipe", RECIPE)
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)

    def recipe(self, grpc=False):
        recipe = self.module.WorkraveDependencies()
        recipe.cross = True
        recipe.options = SimpleNamespace(with_grpc=grpc)
        recipe.requires = Mock()
        recipe.tool_requires = Mock()
        return recipe

    def test_updater_libraries_are_required_with_grpc_disabled(self):
        recipe = self.recipe()
        recipe.requirements()
        requirements = [call.args[0] for call in recipe.requires.call_args_list]
        self.assertIn("protobuf/6.33.5", requirements)
        self.assertIn("abseil/20260817.0", requirements)
        self.assertNotIn("grpc/1.84.0", requirements)

    def test_native_protoc_is_required_with_grpc_disabled(self):
        recipe = self.recipe()
        recipe.build_requirements()
        tools = [call.args[0] for call in recipe.tool_requires.call_args_list]
        self.assertIn("protobuf/6.33.5", tools)
        self.assertNotIn("grpc/1.84.0", tools)

    def test_grpc_still_adds_its_library_and_generator(self):
        recipe = self.recipe(grpc=True)
        recipe.requirements()
        recipe.build_requirements()
        self.assertIn("grpc/1.84.0", [call.args[0] for call in recipe.requires.call_args_list])
        self.assertIn("grpc/1.84.0", [call.args[0] for call in recipe.tool_requires.call_args_list])

    def test_cross_toolchain_selects_cached_host_protoc_without_grpc(self):
        recipe = self.recipe()
        recipe.settings_build = SimpleNamespace(os="Linux", arch="x86_64")
        class Dependencies(SimpleNamespace):
            def __getitem__(self, name):
                return self.host[name]

        recipe.dependencies = Dependencies(
            host={"qt": SimpleNamespace(cpp_info=SimpleNamespace(components={}))},
            direct_build={name: SimpleNamespace(package_folder=f"/cached host/{name}")
                          for name in ("qt", "protobuf")})
        with tempfile.TemporaryDirectory(prefix="updater generators ") as temporary:
            recipe.generators_folder = temporary
            recipe.generate()
            variables = recipe.generated_toolchain.variables
            self.assertEqual(variables["Protobuf_PROTOC_EXECUTABLE"], "/cached host/protobuf/bin/protoc")
            tools = (Path(temporary) / "workrave-host-tools.cmake").read_text()
            self.assertIn("protobuf::protoc", tools)
            self.assertIn("/cached host/protobuf/bin/protoc", tools)
            self.assertNotIn("grpc_cpp_plugin", tools)


if __name__ == "__main__":
    unittest.main()
