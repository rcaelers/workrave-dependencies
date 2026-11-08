#!/usr/bin/env python3
"""Install project-local Conan configuration and the small CCI recipe overlays."""

import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CCI_COMMIT = "08d9ba53fce3cf3d5a9157da1fdecd32371c452a"
CCI_SHA256 = "4f6296e62a475a022a7c7b60b6fabb3ec1c3c756cd70a12c98ce1e26bb9a7082"
OVERLAYS = {
    "qt": ("6.x.x", "6.12.0"),
    "boost": ("all", "1.91.0"),
    "openssl": ("3.x.x", "3.6.5"),
    "grpc": ("all", "1.84.0"),
    "abseil": ("all", "20260107.1"),
    "protobuf": ("all", "6.33.5"),
}


def main():
    if not os.environ.get("CONAN_HOME"):
        raise SystemExit("Set CONAN_HOME to a dedicated cache before running setup.py")
    subprocess.run(["conan", "config", "install", str(ROOT / "config")], check=True)
    cache = ROOT / "_cache"
    cache.mkdir(exist_ok=True)
    archive = cache / f"conan-center-index-{CCI_COMMIT}.tar.gz"
    if not archive.exists():
        url = f"https://codeload.github.com/conan-io/conan-center-index/tar.gz/{CCI_COMMIT}"
        with urllib.request.urlopen(url) as response, archive.open("wb") as target:
            shutil.copyfileobj(response, target)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != CCI_SHA256:
        raise SystemExit(f"Checksum mismatch: remove {archive} and retry")

    with tempfile.TemporaryDirectory(prefix="workrave-cci-") as temporary:
        with tarfile.open(archive) as source:
            prefixes = tuple(
                f"conan-center-index-{CCI_COMMIT}/recipes/{name}/{folder}/"
                for name, (folder, _) in OVERLAYS.items()
            )
            members = [
                item for item in source.getmembers() if item.name.startswith(prefixes)
            ]
            source.extractall(temporary, members=members, filter="data")
        for name, (folder, version) in OVERLAYS.items():
            recipe = (
                Path(temporary)
                / f"conan-center-index-{CCI_COMMIT}/recipes/{name}/{folder}"
            )
            subprocess.run(
                [
                    "patch",
                    "--batch",
                    "--fuzz=0",
                    "-p1",
                    "-i",
                    str(ROOT / "patches" / f"{name}-llvm-mingw.patch"),
                ],
                cwd=recipe,
                check=True,
            )
            extras = ROOT / "recipes" / name
            if extras.is_dir():
                shutil.copytree(extras, recipe, dirs_exist_ok=True)
            subprocess.run(
                ["conan", "export", str(recipe), f"--version={version}"], check=True
            )


if __name__ == "__main__":
    main()
