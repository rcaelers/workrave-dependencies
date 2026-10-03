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
CCI_COMMIT = "07389b8fa043666661da208a0cff039338f6e596"
CCI_SHA256 = "adb15503f3b3ab4b98a45bc7d77ff01497c738d99ab8db8a2f52f54bb8fff5e9"
OVERLAYS = {
    "qt": ("6.x.x", "6.11.1"),
    "boost": ("all", "1.91.0"),
    "openssl": ("3.x.x", "3.6.4"),
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
            subprocess.run(
                ["conan", "export", str(recipe), f"--version={version}"], check=True
            )


if __name__ == "__main__":
    main()
