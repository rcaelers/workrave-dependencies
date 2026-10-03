"""Keep matching PDBs in Conan packages, including when recipes discard them."""

import hashlib
import json
import shutil
import struct
import uuid
from pathlib import Path

from conan.errors import ConanException


def pe_debug_info(filename):
    data = Path(filename).read_bytes()
    if data[:2] != b"MZ":
        raise ValueError(f"Not a PE image: {filename}")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe : pe + 4] != b"PE\0\0":
        raise ValueError(f"Invalid PE signature: {filename}")
    machine, sections = struct.unpack_from("<HH", data, pe + 4)
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    directory = optional + {0x10B: 96, 0x20B: 112}[magic]
    debug_rva, debug_size = struct.unpack_from("<II", data, directory + 6 * 8)
    for index in range(sections):
        section = optional + optional_size + 40 * index
        virtual_size, rva, raw_size, raw = struct.unpack_from(
            "<IIII", data, section + 8
        )
        if rva <= debug_rva < rva + max(virtual_size, raw_size):
            offset = raw + debug_rva - rva
            for entry in range(offset, offset + debug_size, 28):
                kind, size, _, pointer = struct.unpack_from("<IIII", data, entry + 12)
                if kind == 2 and data[pointer : pointer + 4] == b"RSDS":
                    guid = uuid.UUID(
                        bytes_le=data[pointer + 4 : pointer + 20]
                    ).hex.upper()
                    age = struct.unpack_from("<I", data, pointer + 20)[0]
                    name = data[pointer + 24 : pointer + size].split(b"\0")[0].decode()
                    if name:
                        return (
                            machine,
                            guid,
                            age,
                            name.replace("\\", "/").rsplit("/", 1)[-1],
                        )
    raise ValueError(f"No PDB CodeView record: {filename}")


def pdb_identity(filename):
    # PDB 7's information stream stores the same GUID and age as PE/RSDS.
    with Path(filename).open("rb") as source:
        header = source.read(56)
        if not header.startswith(b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0"):
            raise ValueError(f"Not a PDB 7 file: {filename}")
        block_size, _, _, directory_size, _, block_map = struct.unpack_from(
            "<6I", header, 32
        )

        def blocks(numbers):
            result = bytearray()
            for number in numbers:
                source.seek(number * block_size)
                result.extend(source.read(block_size))
            return result

        count = (directory_size + block_size - 1) // block_size
        source.seek(block_map * block_size)
        directory_blocks = struct.unpack(f"<{count}I", source.read(count * 4))
        directory = blocks(directory_blocks)[:directory_size]
        stream_count = struct.unpack_from("<I", directory)[0]
        sizes = struct.unpack_from(f"<{stream_count}I", directory, 4)
        offset = 4 + 4 * stream_count
        for index, size in enumerate(sizes):
            count = 0 if size == 0xFFFFFFFF else (size + block_size - 1) // block_size
            numbers = struct.unpack_from(f"<{count}I", directory, offset)
            offset += 4 * count
            if index == 1:
                info = blocks(numbers)
                age = struct.unpack_from("<I", info, 8)[0]
                return uuid.UUID(bytes_le=bytes(info[12:28])).hex.upper(), age
    raise ValueError(f"No PDB information stream: {filename}")


def retain_symbols(package_folder, build_folder, arch, source_folder=None):
    package, build = Path(package_folder), Path(build_folder)
    candidates = {}
    # Some Autotools recipes compile in their copied source tree, outside the
    # layout's build_folder (notably OpenSSL).
    roots = (package, build, Path(source_folder)) if source_folder else (package, build)
    for root in roots:
        for candidate in root.rglob("*"):
            if candidate.suffix.lower() == ".pdb" and candidate.is_file():
                candidates.setdefault(candidate.name.lower(), []).append(candidate)
    manifest = []
    expected_machine = {"x86_64": 0x8664, "armv8": 0xAA64}[arch]
    for binary in sorted(package.rglob("*")):
        if not binary.is_file() or binary.suffix.lower() not in (".dll", ".exe"):
            continue
        machine, guid, age, name = pe_debug_info(binary)
        if machine != expected_machine:
            raise ValueError(f"Wrong architecture in {binary}: {machine:#x}")
        matching = [
            pdb
            for pdb in candidates.get(name.lower(), [])
            if pdb_identity(pdb) == (guid, age)
        ]
        if not matching:
            raise ValueError(f"No matching PDB for {binary} ({name}, {guid}/{age})")
        destination = package / "symbols" / f"{guid}{age:X}" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if matching[0].resolve() != destination.resolve():
            shutil.copy2(matching[0], destination)
        manifest.append(
            {
                "binary": binary.relative_to(package).as_posix(),
                "pdb": destination.relative_to(package).as_posix(),
                "debug_id": f"{guid}{age:X}",
                "arch": arch,
                "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            }
        )
    if manifest:
        (package / "symbols" / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
    return manifest


def post_package(conanfile):
    if not conanfile.conf.get("user.workrave:toolchain", default="").endswith(
        "-pdb-v1"
    ):
        return
    if conanfile.settings.get_safe("os") != "Windows":
        return
    try:
        manifest = retain_symbols(
            conanfile.package_folder,
            conanfile.build_folder,
            str(conanfile.settings.arch),
            conanfile.source_folder,
        )
    except (ValueError, KeyError, struct.error) as error:
        raise ConanException(f"Symbol verification failed: {error}") from error
    if manifest:
        conanfile.output.info(
            f"Retained matching PDBs for {len(manifest)} Windows binaries"
        )
