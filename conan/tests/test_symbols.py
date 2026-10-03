"""Exercise symbol preservation against real llvm-mingw PE/PDB pairs."""

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = (
    Path(__file__).resolve().parents[1]
    / "config/extensions/hooks/hook_workrave_symbols.py"
)
spec = importlib.util.spec_from_file_location("symbols", HOOK)
symbols = importlib.util.module_from_spec(spec)
spec.loader.exec_module(symbols)


@unittest.skipUnless(
    shutil.which("x86_64-w64-mingw32-clang"), "requires the build image"
)
class SymbolsTest(unittest.TestCase):
    def build(self, folder, target, value=42):
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / "example.c"
        source.write_text(
            f"__declspec(dllexport) int answer(void) {{ return {value}; }}\n"
        )
        subprocess.run(
            [
                f"{target}-w64-mingw32-clang",
                "-shared",
                "-g",
                "-gcodeview",
                str(source),
                "-o",
                str(folder / "example.dll"),
                f"-Wl,--pdb={folder / 'example.pdb'}",
            ],
            check=True,
            capture_output=True,
        )
        return folder / "example.dll"

    def test_preserve_both_architectures(self):
        for arch, target in (("x86_64", "x86_64"), ("armv8", "aarch64")):
            with self.subTest(arch=arch), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                binary = self.build(root / "build", target)
                package = root / "package"
                package.mkdir()
                shutil.copy2(binary, package)
                # The recipe installed the DLL but discarded the PDB.
                manifest = symbols.retain_symbols(package, binary.parent, arch)
                self.assertEqual(len(manifest), 1)
                pdb = package / manifest[0]["pdb"]
                self.assertEqual(
                    pdb.read_bytes(), (binary.parent / "example.pdb").read_bytes()
                )
                shutil.rmtree(binary.parent)
                # Symbols survive removal of the build cache and can be rechecked.
                self.assertEqual(
                    symbols.retain_symbols(package, root / "absent", arch), manifest
                )

    def test_reject_mismatched_pdb(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = self.build(root / "first", "x86_64", 1)
            self.build(root / "second", "x86_64", 2)
            package = root / "package"
            package.mkdir()
            shutil.copy2(binary, package)
            with self.assertRaisesRegex(ValueError, "No matching PDB"):
                symbols.retain_symbols(package, root / "second", "x86_64")

    def test_in_source_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = self.build(root / "source", "x86_64")
            package = root / "package"
            package.mkdir()
            shutil.copy2(binary, package)
            manifest = symbols.retain_symbols(
                package, root / "build", "x86_64", root / "source"
            )
            self.assertEqual(len(manifest), 1)

    @unittest.skipUnless(
        shutil.which("dump_syms"), "requires dump_syms from the build image"
    )
    def test_breakpad_conversion(self):
        for target, cpu in (("x86_64", "x86_64"), ("aarch64", "arm64")):
            with (
                self.subTest(target=target),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                self.build(root, target)
                guid, age = symbols.pdb_identity(root / "example.pdb")
                result = subprocess.run(
                    ["dump_syms", str(root / "example.pdb")],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertTrue(
                    result.stdout.startswith(
                        f"MODULE windows {cpu} {guid}{age:X} example.pdb\n"
                    )
                )
                self.assertIn("answer", result.stdout)
                self.assertRegex(result.stdout, r"(?m)^FUNC ")
                self.assertRegex(result.stdout, r"(?m)^FILE .*example.c")

    def test_reject_wrong_architecture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = self.build(root / "build", "x86_64")
            package = root / "package"
            package.mkdir()
            shutil.copy2(binary, package)
            with self.assertRaisesRegex(ValueError, "Wrong architecture"):
                symbols.retain_symbols(package, binary.parent, "armv8")

    def test_reject_missing_codeview(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "example.c"
            source.write_text("__declspec(dllexport) int answer(void) { return 42; }\n")
            subprocess.run(
                [
                    "x86_64-w64-mingw32-clang",
                    "-shared",
                    str(source),
                    "-o",
                    str(root / "example.dll"),
                ],
                check=True,
                capture_output=True,
            )
            with self.assertRaisesRegex(ValueError, "No PDB CodeView record"):
                symbols.retain_symbols(root, root / "absent", "x86_64")


if __name__ == "__main__":
    unittest.main()
