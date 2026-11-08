"""Assemble universal Conan packages and relocatable CMakeDeps metadata.

Conan owns the thin packages. Only exported copies are merged or patched.
Consumers need CMake and Xcode, but do not need Conan or its original cache.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ARCHES = ("arm64", "x86_64")
QT_SHELL_TOOLS = {"qt-cmake", "qt-cmake-create", "qt-configure-module", "qt-cmake-private",
                  "qt-internal-configure-tests", "qt-internal-configure-examples"}
MACH_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def is_binary(path):
    with path.open("rb") as source:
        magic = source.read(8)
    return magic[:4] in MACH_MAGICS or magic == b"!<arch>\n"


def architectures(path):
    return set(run("lipo", "-archs", path).split())


def check_deployment_target(path, maximum):
    if path.suffix == ".a":
        return
    commands = run("otool", "-l", path)
    versions = re.findall(r"\bminos (\d+(?:\.\d+)*)", commands)
    versions += re.findall(r"cmd LC_VERSION_MIN_MACOSX\n\s+cmdsize \d+\n\s+version (\d+(?:\.\d+)*)", commands)
    def number(version):
        return tuple((list(map(int, version.split("."))) + [0, 0, 0])[:3])
    if not versions or any(number(version) > number(maximum) for version in versions):
        raise RuntimeError(f"Wrong macOS deployment target: {path}: {versions}; expected <= {maximum}")


def host_packages(graph):
    nodes = [n for n in graph["nodes"].values() if n.get("context") == "host" and n.get("ref")]
    result = {}
    for node in nodes:
        if not node.get("package_folder"):
            raise RuntimeError(f"Missing exported package: {node['ref']}; disable skipped binaries")
        if node["name"] in result:
            raise RuntimeError(f"Duplicate host package: {node['name']}")
        result[node["name"]] = node
    return result


def path_mappings(graph):
    mappings = {}
    hosts = host_packages(graph)
    for node in graph["nodes"].values():
        name = node.get("name")
        if node.get("package_folder") and name in hosts:
            # Cross-built Qt/protobuf import native build tools; the exported
            # package has universal tools, so redirect those imports too.
            mappings[node["package_folder"]] = f"@WORKRAVE_SDK_ROOT@/packages/{name}"
    return mappings


def relocate(text, mappings):
    for old, new in sorted(mappings.items(), key=lambda item: -len(item[0])):
        text = text.replace(old, new)
    return text


def cmake_text(text, path, destination, mappings):
    text = normalize_metadata(relocate(text, mappings), path)
    if path.parent.name == "generators":
        # The SDK has one set of headers. Workrave inspects imported include
        # directories for configuration-time compiler probes, whose nested
        # try_compile may have no Release configuration selected.
        text = re.sub(r'\$<\$<CONFIG:Release>:(\$\{[^}]+_INCLUDE_DIRS_RELEASE\})>', r'\1', text)
    # Cached Qt packages can refer to the native Qt package used when they
    # were built, rather than to the one in the current consumer graph.
    for old in mappings:
        if "/p/" in old:
            cache = old.split("/p/", 1)[0]
            text = re.sub(re.escape(cache) + r"/p/(?:b/)?qt[^/]+/p(?=[/\";)])",
                          "@WORKRAVE_SDK_ROOT@/packages/qt", text)
    if path.name == "qt.toolchain.cmake":
        text = re.sub(r"set\(__qt_initially_configured_toolchain_file [^\n]+",
                      'set(__qt_initially_configured_toolchain_file "@WORKRAVE_SDK_ROOT@/toolchain.cmake")', text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    if "@WORKRAVE_SDK_ROOT@" in text:
        relative = os.path.relpath(destination, path.parent).replace(os.sep, "/")
        # Use a file-local variable. No environment setup or configure-time
        # replacement is needed after moving the SDK.
        text = (f'get_filename_component(_workrave_sdk_root "${{CMAKE_CURRENT_LIST_DIR}}/{relative}" ABSOLUTE)\n'
                + text.replace("@WORKRAVE_SDK_ROOT@", "${_workrave_sdk_root}"))
    return text


def normalize_metadata(text, path):
    if path.name in QT_SHELL_TOOLS:
        text = re.sub(r'(?m)^original_cmake_path=.*$', 'original_cmake_path=""', text)
        original = 'script_dir_path=`dirname $0`\nscript_dir_path=`(cd "$script_dir_path"; pwd)`'
        resolved = '''_workrave_script="$0"
while [ -L "$_workrave_script" ]; do
    _workrave_dir=$(CDPATH= cd -- "$(dirname -- "$_workrave_script")" && pwd) || exit 1
    _workrave_link=$(readlink "$_workrave_script") || exit 1
    case "$_workrave_link" in
        /*) _workrave_script="$_workrave_link" ;;
        *) _workrave_script="$_workrave_dir/$_workrave_link" ;;
    esac
done
script_dir_path=$(CDPATH= cd -- "$(dirname -- "$_workrave_script")" && pwd) || exit 1'''
        text = text.replace(original, resolved)
    if path.suffix == ".cmake":
        # These imported-target properties identify/checksum the thin input
        # inventories, not our merged SDK. The original documents are retained
        # separately; do not attach a false SBOM identity to exported targets.
        text = re.sub(r'(?m)^  _qt_sbom_[^\n]*\n', '', text)
        def cmake_features(match):
            values = [v for v in match[2].split(';') if v and v != 'cross_compile']
            if path.name == 'Qt6CoreTargets.cmake' and match[1] == 'QT_DISABLED_PUBLIC_FEATURES':
                values.append('cross_compile')
            return f'  {match[1]} "{";".join(values)}"'
        text = re.sub(r'(?m)^  (QT_(?:ENABLED|DISABLED)_(?:PRIVATE|PUBLIC)_FEATURES|QT_QMAKE_(?:PRIVATE|PUBLIC)_CONFIG) "([^"\n]*)"$',
                      cmake_features, text)
    if path.name == "Qt6Dependencies.cmake":
        text = text.replace('set(__qt_platform_requires_host_info_package "TRUE")',
                            'set(__qt_platform_requires_host_info_package "FALSE")')
        for variable in ("__qt_platform_initial_qt_host_path", "__qt_platform_initial_qt_host_path_cmake_dir"):
            text = re.sub(r'set\(' + variable + r' "[^"]*"\)', f'set({variable} "")', text)
    if path.name == "Qt6HostInfoConfig.cmake":
        text = re.sub(r'set\(QT6_HOST_INFO_ARCH "[^"]*"\)',
                      'set(QT6_HOST_INFO_ARCH "${CMAKE_HOST_SYSTEM_PROCESSOR}")', text)
        text = re.sub(r'set\(QT6_HOST_INFO_SUBARCHS "[^"]*"\)', 'set(QT6_HOST_INFO_SUBARCHS "")', text)
    if path.name.endswith("TargetsPrecheck.cmake"):
        text = re.sub(r'(?m)^    TARGETS (.+)$', lambda m: '    TARGETS ' + m[1].replace('_native', ''), text)
    if path.name == "Qt6Targets.cmake":
        intel_cet = r'\$<\$<NOT:\$<BOOL:\$<TARGET_PROPERTY:_qt_no_intel_cet_harderning>>>:-fcf-protection=full>;'
        text = text.replace(intel_cet, '')
        universal_cet = r'\$<\$<NOT:\$<BOOL:\$<TARGET_PROPERTY:_qt_no_intel_cet_harderning>>>:SHELL:-Xarch_x86_64 -fcf-protection=full>;'
        text = text.replace('INTERFACE_COMPILE_OPTIONS "-ftrivial-auto-var-init=pattern;',
                            'INTERFACE_COMPILE_OPTIONS "' + universal_cet + '-ftrivial-auto-var-init=pattern;')
    if path.name in ("qconfig.pri", "qmodule.pri") and text.startswith("host_build {\n"):
        block = re.match(r"host_build \{\n(.*?)\n\} else \{\n(.*?)\n\}\n", text, re.S)
        if not block:
            raise RuntimeError(f"Unrecognized Qt host/target metadata: {path}")
        branches = [[line.lstrip() for line in branch.splitlines() if line.strip()]
                    for branch in block.groups()]
        allowed = (r"QT_(?:ARCH|BUILDABI|TARGET_ARCH|TARGET_BUILDABI|LIBCPP_ABI_TAG) =.*"
                   if path.name == "qconfig.pri" else r"QT_CPU_FEATURES\.[^ =]+ =.*")
        if not all(re.fullmatch(allowed, line) for branch in branches for line in branch):
            raise RuntimeError(f"Unexpected Qt host/target metadata: {path}")
        # The exported native tools are universal, so there is no permanent
        # host/target split. Keep both CPUs' capabilities; ABI defaults come
        # from the target branch (the native profile supplies the same fields).
        lines = branches[1] if path.name == "qconfig.pri" else branches[0] + branches[1]
        text = "\n".join(lines) + "\n" + text[block.end():]
    if path.name == "xml2-config":
        if '_workrave_script="$0"' in text:
            return text
        # Resolve the SDK's bin/ symlink before computing the package prefix.
        prefix = '''_workrave_script="$0"
while [ -L "$_workrave_script" ]; do
    _workrave_dir=$(CDPATH= cd -- "$(dirname -- "$_workrave_script")" && pwd) || exit 1
    _workrave_link=$(readlink "$_workrave_script") || exit 1
    case "$_workrave_link" in
        /*) _workrave_script="$_workrave_link" ;;
        *) _workrave_script="$_workrave_dir/$_workrave_link" ;;
    esac
done
prefix=$(CDPATH= cd -- "$(dirname -- "$_workrave_script")/.." && pwd) || exit 1'''
        text = re.sub(r"(?m)^prefix=.*", lambda _: prefix, text)
    if path.name == "c_rehash":
        if "$FindBin::RealBin/../res" in text:
            return text
        if text.startswith("#!perl\n"):
            text = text.replace("#!perl\n", "#!/usr/bin/perl\n", 1)
        # OpenSSL's Perl helper otherwise retains its package-cache openssldir
        # and the staging prefix "/". FindBin follows the SDK entry symlink.
        text = re.sub(r"(?m)^my \$dir = .*;", 'use FindBin ();\nmy $dir = "$FindBin::RealBin/../res";', text)
        text = re.sub(r"(?m)^my \$prefix = .*;", 'my $prefix = "$FindBin::RealBin/..";', text)
    if path.name == "qt.toolchain.cmake":
        # A native build records its original compiler; a cross build instead
        # records a permanent target architecture/system. Neither should
        # override the consumer's compiler or turn a universal SDK into an
        # Intel-only cross toolchain.
        text = re.sub(r'set\(__qt_initial_c_compiler [^\n]*\n'
                      r'set\(__qt_initial_cxx_compiler [^\n]*\n'
                      r'if\(QT_USE_ORIGINAL_COMPILER.*?\nendif\(\)\n'
                      r'if\(QT_USE_ORIGINAL_COMPILER.*?\nendif\(\)\n', '', text, flags=re.S)
        text = re.sub(r'if\(NOT __qt_toolchain_building_qt_repo AND NOT QT_NO_SET_OSX_ARCHITECTURES\)\n'
                      r'    set\(CMAKE_OSX_ARCHITECTURES "(?:arm64|x86_64)" CACHE STRING ""\)\n'
                      r'    set\(CMAKE_SYSTEM_NAME "Darwin" CACHE STRING ""\)\nendif\(\)\n', '', text)
        text = re.sub(r'set\(QT_OSX_ARCHITECTURES "[^"]*"',
                      'set(QT_OSX_ARCHITECTURES "arm64;x86_64"', text)
        text = re.sub(r"set\(__qt_initially_configured_toolchain_file [^\n]+",
                      'set(__qt_initially_configured_toolchain_file "@WORKRAVE_SDK_ROOT@/toolchain.cmake")', text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    if path.name == "qconfig.pri":
        text = re.sub(r"(?m)^QT_ARCH = .*", "QT_ARCH = arm64", text)
        text = re.sub(r"(?m)^QT_ARCHS = .*", "QT_ARCHS = arm64 x86_64", text)
    if path.suffix == ".pri":
        # The exported tools themselves run on both architectures; the Intel
        # slice's build-time cross-compilation marker must not configure the
        # universal SDK as a permanently cross-only qmake installation.
        def features(match):
            prefix, tokens = match[1], match[2].split()
            tokens = [token for token in tokens if token != "cross_compile"]
            if prefix == "QT.global.disabled_features = ":
                tokens.append("cross_compile")
            return prefix + " ".join(tokens)
        text = re.sub(r"(?m)^((?:QT\.[^ =]+\.(?:enabled|disabled)_features|QT_CONFIG|CONFIG) \+?= )(.*)$", features, text)
    if path.name == "qmldir" and path.parent.name == "QmlTime":
        text = text.replace("typeinfo qmltime_native.qmltypes", "typeinfo qmltime.qmltypes")
    if path.suffix == ".prl":
        # This is build-tree provenance, not an installed link dependency.
        text = re.sub(r"(?m)^QMAKE_PRL_BUILD_DIR = .*\n?", "", text)
    return text


def architecture_feature(value):
    return re.fullmatch(r'(?:x86intrin|sse.*|ssse.*|avx.*|f16c|aesni|vaes|rdrnd|rdseed|shani|intelcet|neon|arm_.*|mips_dsp.*|lsx|lasx|qml[-_]jit)', value)


def merge_cmake_features(left, right):
    pattern = re.compile(r'(?m)^  (QT_(?:ENABLED|DISABLED)_(?:PRIVATE|PUBLIC)_FEATURES|QT_QMAKE_(?:PRIVATE|PUBLIC)_CONFIG) "([^"\n]*)"$')
    records = [{m[1]: m[2].split(';') if m[2] else [] for m in pattern.finditer(text)} for text in (left, right)]
    if pattern.sub('', left) != pattern.sub('', right) or records[0].keys() != records[1].keys():
        raise RuntimeError('Different non-feature CMake metadata')
    merged = {}
    for name, a in records[0].items():
        b = records[1][name]
        if any(not architecture_feature(v) for v in set(a) ^ set(b)):
            raise RuntimeError(f'Different non-architecture CMake features: {name}')
        # A universal consumer may only assume capabilities shared by both
        # slices. The architecture-dispatched headers retain the full actual
        # feature definitions for each compiler invocation.
        values = list(dict.fromkeys(a + b)) if 'DISABLED' in name else [v for v in a if v in b]
        merged[name] = f'  {name} "{";".join(values)}"'
    return pattern.sub(lambda m: merged[m[1]], left)


def merge_qmake_features(left, right):
    """Combine CPU capabilities, while requiring all other features to agree."""
    pattern = re.compile(r"(?m)^(QT_CPU_FEATURES\.[^ =]+|QT\.[^ =]+\.(?:enabled|disabled)_features|QT_CONFIG|CONFIG) (\+?=) (.*)$")
    values = [list(pattern.finditer(text)) for text in (left, right)]
    records = [{(m[1], m[2]): m[3].split() for m in matches} for matches in values]
    remaining = [[line for line in pattern.sub("", text).splitlines() if line.strip()]
                 for text in (left, right)]
    if remaining[0] != remaining[1]:
        raise RuntimeError("Different non-feature qmake configuration")
    lines = []
    for key in dict.fromkeys([*records[0], *records[1]]):
        name, operator = key
        a, b = (record.get(key, []) for record in records)
        if name.startswith("QT_CPU_FEATURES."):
            if key in records[0] and key in records[1] and a != b:
                raise RuntimeError(f"Different capabilities for the same CPU: {name}")
            combined = a or b
        else:
            if [v for v in a if not architecture_feature(v)] != [v for v in b if not architecture_feature(v)]:
                raise RuntimeError(f"Different non-CPU Qt features: {name}")
            combined = (list(dict.fromkeys(a + b)) if ".disabled_features" in name
                        else [v for v in a if v in b])
        lines.append(f'{name} {operator} {" ".join(combined)}\n')
    return "".join(lines) + pattern.sub("", left).lstrip("\n")


def merge_file(left, right, target, mappings, report):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix == ".spdx" and target.parent.name == "sbom":
        # Qt's documents describe/checksum the original thin build outputs.
        # Neither is a valid inventory of the merged, relocated binaries.
        # Retain both as source provenance rather than choosing one or
        # rewriting its signed-off identities/checksums into a synthetic SBOM.
        for arch, source in zip(ARCHES, (left, right)):
            directory = target.parent / arch
            directory.mkdir(exist_ok=True)
            shutil.copy2(source, directory / target.name)
        (target.parent / "README.txt").write_text(
            "These architecture-specific SPDX documents describe the original\n"
            "Conan package inputs, before universal merging, relocation and\n"
            "ad-hoc signing. Their binary checksums do not describe this SDK.\n")
        report["source_sboms"] = report.get("source_sboms", 0) + 2
        return
    if left.is_symlink() or right.is_symlink():
        if not left.is_symlink() or not right.is_symlink():
            raise RuntimeError(f"Symlink differs between architectures: {left}")
        links = []
        for source, mapping in zip((left, right), mappings):
            link = os.readlink(source)
            if os.path.isabs(link):
                relocated = relocate(link, mapping)
                if not relocated.startswith("@WORKRAVE_SDK_ROOT@/"):
                    raise RuntimeError(f"External symlink: {source} -> {link}")
                # Absolute package symlinks are rewritten by the caller's
                # export pass below, once the SDK root is known.
                link = relocated
            links.append(link)
        if links[0] != links[1]:
            raise RuntimeError(f"Symlink targets differ: {left}: {links}")
        target.symlink_to(links[0])
        return
    if is_binary(left) or is_binary(right):
        if not is_binary(left) or not is_binary(right):
            raise RuntimeError(f"Binary missing in one architecture: {left}")
        # Even byte-identical files must be checked: an accidentally reused
        # thin tool/library must never pass as universal.
        inputs = []
        for arch, source in zip(ARCHES, (left, right)):
            available = architectures(source)
            if arch not in available:
                raise RuntimeError(f"{source} has {available}, expected {arch}")
            if available == {arch}:
                inputs.append(source)
            else:
                thin = target.with_name(target.name + f".{arch}.tmp")
                run("lipo", source, "-thin", arch, "-output", thin)
                inputs.append(thin)
        try:
            run("lipo", "-create", *inputs, "-output", target)
        finally:
            for item, source in zip(inputs, (left, right)):
                if item != source:
                    item.unlink()
        shutil.copymode(left, target)
        report["binaries"] += 1
        return
    contents = [p.read_bytes() for p in (left, right)]
    if contents[0] == contents[1]:
        shutil.copy2(left, target)
        return
    try:
        texts = [normalize_metadata(relocate(c.decode("utf-8"), m), target)
                 for c, m in zip(contents, mappings)]
    except UnicodeDecodeError as error:
        raise RuntimeError(f"Different non-text package files: {left}") from error
    if texts[0] == texts[1]:
        target.write_text(texts[0])
    elif target.suffix == ".json" and target.parent.name == "modules" and "qt" in target.parts:
        # macdeployqt reads Qt's module descriptions. Advertise both slices,
        # retaining all other module/platform fields only when they agree.
        modules = [json.loads(text) for text in texts]
        if modules[0].get("schema_version") != 3 or modules[1].get("schema_version") != 3:
            raise RuntimeError(f"Unsupported Qt module metadata: {left}")
        platforms = [module.pop("platforms", []) for module in modules]
        if modules[0] != modules[1]:
            raise RuntimeError(f"Different Qt module configuration: {left}")
        # Native CMake records the running Darwin version; cross CMake records
        # its configured target Darwin version. Preserve both provenance
        # records when those versions differ, combining matching records.
        signatures = [[{k: v for k, v in p.items() if k not in ("targets", "version")}
                       for p in current] for current in platforms]
        if signatures[0] != signatures[1]:
            raise RuntimeError(f"Different Qt module platform/compiler: {left}")
        merged = platforms[0]
        for platform in platforms[1]:
            identity = {k: v for k, v in platform.items() if k != "targets"}
            match = next((p for p in merged if {k: v for k, v in p.items() if k != "targets"} == identity), None)
            if match is None:
                merged.append(platform)
            else:
                match["targets"] = match.get("targets", []) + [t for t in platform.get("targets", [])
                                                               if t not in match.get("targets", [])]
        modules[0]["platforms"] = merged
        target.write_text(json.dumps(modules[0], indent=4) + "\n")
    elif target.suffix == ".pri":
        target.write_text(merge_qmake_features(*texts))
    elif target.suffix == ".cmake":
        target.write_text(merge_cmake_features(*texts))
    elif target.suffix in (".h", ".hpp", ".hxx", ".inc"):
        # Generated configuration headers can legitimately differ. Preserve
        # both definitions and let the *consumer compiler* select the slice.
        for arch, text in zip(ARCHES, texts):
            sibling = target.with_name(f"{target.stem}.workrave-{arch}{target.suffix}")
            sibling.write_text(text)
        target.write_text(
            '#if defined(__arm64__) || defined(__aarch64__)\n'
            f'#include "{target.stem}.workrave-arm64{target.suffix}"\n'
            '#elif defined(__x86_64__)\n'
            f'#include "{target.stem}.workrave-x86_64{target.suffix}"\n'
            '#else\n#error "Unsupported Workrave SDK architecture"\n#endif\n')
        report["headers"].append(str(target))
    else:
        # Do not silently choose one architecture's metadata or resources.
        raise RuntimeError(f"Architecture-dependent file needs explicit handling: {left}")
    shutil.copymode(left, target)


def merge_package(left, right, target, mappings, report):
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for root in (left, right):
        paths.append({p.relative_to(root): p for p in root.rglob("*")
                      if (p.is_file() or p.is_symlink())
                      and p.name not in ("conaninfo.txt", "conanmanifest.txt")})
    if target.name == "qt":
        # Cross Qt omits deployment tools for unrelated mobile platforms and
        # installs host-only aliases/configuration. This is a macOS SDK; do
        # not export thin mobile tools or build-machine launcher scripts.
        excluded = {Path(p) for p in (
            "bin/androiddeployqt", "bin/androiddeployqt6", "bin/androidtestrunner",
            "bin/harmonydeployqt", "bin/harmonydeployqt6", "bin/harmonyostestrunner",
            "libexec/qt-android-runner.py", "bin/host-qmake", "bin/host-qmake6",
            "bin/host-qtpaths", "bin/host-qtpaths6", "bin/target_qt.conf", "mkspecs/qdevice.pri")}
        for files in paths:
            for relative in excluded:
                files.pop(relative, None)
            native = Path("qml/QmlTime/qmltime_native.qmltypes")
            if native in files:
                files[Path("qml/QmlTime/qmltime.qmltypes")] = files.pop(native)
        differences = paths[0].keys() ^ paths[1].keys()
        jit_headers = {"qv4assemblercommon_p.h", "qv4baselineassembler_p.h", "qv4baselinejit_p.h"}
        for relative in differences:
            if (relative.name not in jit_headers or relative.parts[:2] != ("include", "QtQml")
                    or relative.parent.name != "private"):
                continue
            for arch, files in zip(ARCHES, paths):
                if relative in files:
                    source = files.pop(relative)
                    output = target / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    sibling = output.with_name(f"{output.stem}.workrave-{arch}{output.suffix}")
                    shutil.copy2(source, sibling)
                    macro = "__x86_64__" if arch == "x86_64" else "__arm64__"
                    output.write_text(f'#if defined({macro})\n#include "{sibling.name}"\n'
                                      '#else\n#error "Qt JIT header is unavailable for this architecture"\n#endif\n')
                    report["headers"].append(str(output))
    if paths[0].keys() != paths[1].keys():
        raise RuntimeError(f"Package contents differ: {left}: {paths[0].keys() ^ paths[1].keys()}")
    for relative in sorted(paths[0]):
        # Directory symlinks are copied as symlinks, never followed.
        if any((left / parent).is_symlink() for parent in relative.parents if parent != Path(".")):
            continue
        merge_file(paths[0][relative], paths[1][relative], target / relative, mappings, report)


def export_cmake(generators, destination, mappings):
    output = destination / "generators"
    output.mkdir()
    for source in generators.glob("*.cmake"):
        if source.name in ("conan_toolchain.cmake", "conandeps_legacy.cmake", "workrave-host-tools.cmake"):
            continue
        target = output / source.name
        target.write_text(cmake_text(source.read_text(), target, destination, mappings))
        # Standard CMake package search from CMAKE_PREFIX_PATH=<sdk>.
        # Keep includes relative to the original, shared generators directory.
        name = source.name
        package = None
        if name.endswith("Config.cmake"):
            package = name.removesuffix("Config.cmake")
        elif name.endswith("-config.cmake"):
            package = name.removesuffix("-config.cmake")
        if package:
            wrapper = destination / "lib/cmake" / package
            wrapper.mkdir(parents=True, exist_ok=True)
            preamble = ('get_filename_component(_workrave_sdk_root "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)\n'
                        'list(PREPEND CMAKE_PREFIX_PATH "${_workrave_sdk_root}/generators")\n'
                        'list(PREPEND CMAKE_MODULE_PATH "${_workrave_sdk_root}/generators")\n'
                        'list(PREPEND CMAKE_PROGRAM_PATH "${_workrave_sdk_root}/bin")\n'
                        'set(CMAKE_FIND_PACKAGE_PREFER_CONFIG ON)\n')
            (wrapper / name).write_text(preamble + f'include("${{_workrave_sdk_root}}/generators/{name}")\n')
            for version in (f"{package}ConfigVersion.cmake", f"{package}-config-version.cmake"):
                if (generators / version).exists():
                    (wrapper / version).write_text(preamble + f'include("${{_workrave_sdk_root}}/generators/{version}")\n')
    if not list(output.glob("*Config.cmake")) and not list(output.glob("*-config.cmake")):
        raise RuntimeError(f"No CMakeDeps configuration in {generators}")


def fix_libraries(destination):
    """Remove cache install names/rpaths from exported copies before signing."""
    dylibs = {}
    binaries = []
    for path in destination.rglob("*"):
        if not path.is_file() or not is_binary(path) or path.suffix == ".a":
            continue
        if not path.is_symlink():
            binaries.append(path)
        if path.suffix == ".dylib":
            if path.name in dylibs and dylibs[path.name].resolve() != path.resolve():
                raise RuntimeError(f"Ambiguous dylib name: {path.name}")
            dylibs[path.name] = path.resolve()
    sonames = {}
    for path in binaries:
        if path.suffix != ".dylib":
            continue
        identifiers = re.findall(r"cmd LC_ID_DYLIB\n\s+cmdsize \d+\n\s+name (.*?) \(offset",
                                 run("otool", "-l", path))
        names = {Path(identifier).name for identifier in identifiers}
        if len(names) > 1:
            raise RuntimeError(f"Different dylib identities between slices: {path}: {names}")
        name = next(iter(names), path.name)
        if name not in dylibs or dylibs[name] != path.resolve():
            raise RuntimeError(f"Dylib identity has no matching SDK file: {path}: {name}")
        sonames[path.resolve()] = name
    def rewrite(path, thin):
        args = ["install_name_tool"]
        library_dirs = set()
        changed = set()
        if path.suffix == ".dylib":
            args += ["-id", f"@rpath/{sonames[path.resolve()]}"]
        dependencies = run("otool", "-L", thin)
        for line in dependencies.splitlines():
            match = re.match(r"\s+(.+?) \(compatibility version", line)
            if not match:
                continue
            old = match[1]
            name = Path(old).name
            if name in dylibs:
                # Keep @rpath dependencies so macdeployqt discovers/copies
                # them. @loader_path dependencies are skipped by that tool.
                relative = os.path.relpath(dylibs[name].parent, path.parent)
                library_dirs.add(f"@loader_path/{relative}")
                # The app and every plugin must refer to one canonical file.
                # Copying both a major-version alias and a full-version name
                # into an app produces independent Qt images/registrations.
                new = f"@rpath/{sonames[dylibs[name]]}"
                if old != new and old not in changed:
                    args += ["-change", old, new]
                    changed.add(old)
            elif not old.startswith(("/usr/lib/", "/System/Library/")):
                raise RuntimeError(f"Unbundled dependency: {path}: {old}")
        # Keep no original cache or Homebrew rpaths.
        rpaths = set(re.findall(r"cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.*?) \(offset", run("otool", "-l", thin)))
        for rpath in sorted(rpaths - library_dirs):
            args += ["-delete_rpath", rpath]
        for directory in sorted(library_dirs - rpaths):
            args += ["-add_rpath", directory]
        if len(args) > 1:
            # A prior ad-hoc signature is invalidated by install_name_tool.
            # codesign --force below replaces it on both architectures.
            run(*args, thin)
    for path in binaries:
        # Each slice can have different absolute rpaths and dependencies.
        # install_name_tool requires every deleted rpath to exist in every
        # slice, and rejects deleting/re-adding the same rpath in one call.
        with tempfile.TemporaryDirectory(prefix=".workrave-rpaths-", dir=path.parent) as temporary:
            thin_files = []
            for arch in ARCHES:
                thin = Path(temporary) / arch
                run("lipo", path, "-thin", arch, "-output", thin)
                rewrite(path, thin)
                thin_files.append(thin)
            merged = Path(temporary) / "universal"
            run("lipo", "-create", *thin_files, "-output", merged)
            shutil.copymode(path, merged)
            merged.replace(path)
        run("codesign", "--force", "--sign", "-", path)


def write_qt_configuration(destination):
    # Qt's compiled-in locations and QMake's defaults can disagree when a
    # prefix-only qt.conf is present. Set the actual layout explicitly for
    # deployment tools and for the native/cross qmake implementations alike.
    paths = ("Binaries=bin\nLibraries=lib\nLibraryExecutables=libexec\n"
             "Headers=include\nPlugins=plugins\nQmlImports=qml\nTranslations=translations\n"
             "Data=.\nArchData=.\nHostBinaries=bin\nHostLibraries=lib\n"
             "HostLibraryExecutables=libexec\nHostData=.\n")
    # No qt.conf beside the root bin symlinks: on macOS CoreFoundation and
    # QMake can resolve that config against different executable directories,
    # applying packages/qt twice. Use the config beside the actual binary.
    directories = [(destination / "packages/qt/bin", ".."),
                   (destination / "packages/qt/libexec", "..")]
    for directory, prefix in directories:
        if directory.is_dir():
            (directory / "qt.conf").write_text(f"[Paths]\nPrefix={prefix}\nHostPrefix={prefix}\n" + paths)


def _export(arm_build, intel_build, destination):
    graphs = [json.loads((p / "graph.json").read_text())["graph"] for p in (arm_build, intel_build)]
    packages = [host_packages(g) for g in graphs]
    if packages[0].keys() != packages[1].keys():
        raise RuntimeError("The two macOS graphs have different host packages")
    mappings = [path_mappings(g) for g in graphs]
    report = {"binaries": 0, "headers": []}
    manifest = []
    destination.mkdir(parents=True, exist_ok=False)
    for name, node in packages[0].items():
        other = packages[1][name]
        options = [dict(current.get("options", {})) for current in (node, other)]
        if name == "libpng":
            # CCI removes the inapplicable CPU option from each graph. Keep
            # NEON on ARM and SSE on Intel; dispatched headers preserve both.
            for current in options:
                for option in ("sse", "neon"):
                    current.pop(option, None)
        if node["ref"] != other["ref"] or options[0] != options[1]:
            raise RuntimeError(f"Package versions/options differ: {name}")
        settings = [{k: v for k, v in current.get("settings", {}).items() if k != "arch"}
                    for current in (node, other)]
        if settings[0] != settings[1]:
            raise RuntimeError(f"Compiler/deployment settings differ: {name}: {settings}")
        for expected, current in zip(("armv8", "x86_64"), (node, other)):
            settings = current.get("settings", {})
            if settings.get("os") != "Macos" or settings.get("arch", expected) != expected:
                raise RuntimeError(f"Not a macOS {expected} graph: {current['ref']}")
        manifest.append({"ref": node["ref"], "package_ids": [node["package_id"], other["package_id"]],
                         "options": [node.get("options", {}), other.get("options", {})]})
    for name, node in packages[0].items():
        other = packages[1][name]
        target = destination / "packages" / name
        merge_package(Path(node["package_folder"]), Path(other["package_folder"]), target, mappings, report)
    combined = mappings[0] | mappings[1]
    for path in (destination / "packages").rglob("*"):
        if path.is_symlink():
            link = os.readlink(path)
            if link.startswith("@WORKRAVE_SDK_ROOT@/"):
                path.unlink()
                path.symlink_to(os.path.relpath(destination / link.removeprefix("@WORKRAVE_SDK_ROOT@/"), path.parent))
            if not path.exists() or not path.resolve().is_relative_to(destination.resolve()):
                raise RuntimeError(f"Broken or external SDK symlink: {path}")
        elif path.is_file() and path.suffix == ".cmake":
            path.write_text(cmake_text(path.read_text(), path, destination, combined))
        elif path.is_file() and path.name in ({"c_rehash", "xml2-config"} | QT_SHELL_TOOLS):
            path.write_text(normalize_metadata(path.read_text(), path))
        elif path.is_file() and path.suffix == ".json" and path.parent == destination / "packages/qt/modules":
            module = json.loads(path.read_text())
            # Qt 6.12's generator computes bundle_type="none" for dylibs,
            # but accidentally writes the literal "framework" into its JSON.
            if module.get("bundle_type") == "framework":
                module["bundle_type"] = "none"
                path.write_text(json.dumps(module, indent=4) + "\n")
        elif path.is_file() and path.suffix in (".pc", ".prl", ".pri", ".la"):
            text = relocate(path.read_text(), combined)
            relative = os.path.relpath(destination, path.parent).replace(os.sep, "/")
            root = "${pcfiledir}/" + relative if path.suffix == ".pc" else "$$PWD/" + relative
            path.write_text(text.replace("@WORKRAVE_SDK_ROOT@", root))
    export_cmake(arm_build / "build/Release/generators", destination, combined)
    shutil.copy2(Path(__file__).parent / "sdk/macos-toolchain.cmake", destination / "toolchain.cmake")
    # macdeployqt also probes its own bin directory for this private helper.
    # CCI installs the universal binary in libexec; expose that fallback name
    # without duplicating the binary or changing the CMake imported location.
    scanner = destination / "packages/qt/libexec/qmlimportscanner"
    if scanner.exists():
        (destination / "packages/qt/bin/qmlimportscanner").symlink_to("../libexec/qmlimportscanner")
    (destination / "bin").mkdir()
    for package in (destination / "packages").iterdir():
        for tool in (package / "bin").glob("*"):
            link = destination / "bin" / tool.name
            if tool.is_file() and tool.name != "qt.conf":
                if link.exists() or link.is_symlink():
                    raise RuntimeError(f"Conflicting SDK tools: {tool.name}")
                link.symlink_to(os.path.relpath(tool, link.parent))
    write_qt_configuration(destination)
    # Support CMake's built-in Find modules as well as config-mode discovery.
    # In particular FindSQLite3/FindOpenSSL may run before any SDK config has
    # enabled CMAKE_FIND_PACKAGE_PREFER_CONFIG. Keep the familiar single prefix
    # without duplicating files or losing the per-package CMake metadata.
    for package in (destination / "packages").iterdir():
        for directory in ("include", "lib"):
            for source in (package / directory).glob("*"):
                if directory == "lib" and source.suffix not in (".a", ".dylib"):
                    continue
                target = destination / directory / source.name
                target.parent.mkdir(exist_ok=True)
                if target.exists() or target.is_symlink():
                    if target.resolve() != source.resolve():
                        raise RuntimeError(f"Conflicting SDK prefix entries: {target}")
                else:
                    target.symlink_to(os.path.relpath(source, target.parent))
    for name in ("modules", "qml", "plugins", "translations", "libexec", "mkspecs", "resources"):
        source = destination / "packages/qt" / name
        if source.is_dir():
            (destination / name).symlink_to(os.path.relpath(source, destination))
    cache_roots = {old.split("/p/", 1)[0] + "/" for old in combined if "/p/" in old}
    for path in destination.rglob("*.cmake"):
        content = path.read_text()
        if "@WORKRAVE_SDK_ROOT@" in content or any(root in content for root in cache_roots):
            raise RuntimeError(f"Unrelocated Conan cache reference: {path}")
    fix_libraries(destination)
    report["headers"] = [str(Path(p).relative_to(destination)) for p in report["headers"]]
    (destination / "manifest.json").write_text(json.dumps({
        "platform": "macos", "architectures": list(ARCHES), "deployment_target": "14.4", "packages": manifest,
        "merge": report,
    }, indent=2) + "\n")
    lock = Path(__file__).parent / "macos.lock"
    if lock.exists():
        shutil.copy2(lock, destination / "macos.lock")
    for path in destination.rglob("*"):
        if path.is_file() and not path.is_symlink() and is_binary(path):
            if architectures(path) != set(ARCHES):
                raise RuntimeError(f"Non-universal SDK binary: {path}")
            check_deployment_target(path, "14.4")


def export(arm_build, intel_build, destination):
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"SDK output already exists: {destination}")
    # macOS aliases /var and /tmp through /private. Mix neither spelling into
    # loader-relative rpaths, otherwise relocation can embed the staging path.
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A failed merge must not leave an apparently usable partial SDK behind.
    with tempfile.TemporaryDirectory(prefix=".workrave-sdk-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "sdk"
        _export(arm_build, intel_build, staging)
        staging.rename(destination)
