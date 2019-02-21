# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function, unicode_literals

import base64
import csv
import hashlib
import logging
import os
import platform
import py_compile
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zipimport

import pkg_resources
from xar import xar_util
from xar.compat import cache_from_source, native, source_from_cache
from xar.vendor.wheel import install, paths, pkginfo


logger = logging.getLogger("xar")


PYTHON_EXTS = [".py", ".pyc", ".pyo"]


def parse_entry_point(entry_point):
    """
    Parses a Python entry point and returns the module and function.
    The two allowed formats are 'path.to.module', and 'path.to.module:function'.
    In the former case, ('path.to.module', None) is returned.
    In the latter case, ('path.to.module', 'function') is returned.
    """
    module, sep, function = entry_point.partition(":")
    if function and sep and module:
        return (module, function)
    else:
        return (module, None)


def get_python_main(directory):
    """Returns the python __main__ from a directory (if it exists)."""
    main = os.path.join(directory, "__main__")
    main_exists = any(os.path.exists(main + ext) for ext in PYTHON_EXTS)
    if main_exists:
        return "__main__"
    return None


def extract_python_archive_info(archive):
    """
    Extracts the shebang (if any) from a python archive, along with the entry
    point (if any). Returns a tuple (python_interpreter, entry_point).
    Avoids interpreting the shebang in it doesn't contain 'python'.
    """
    python = None
    with open(archive, "rb") as f:
        if f.read(2) == b"#!":
            shebang = f.readline().decode("utf-8").strip()
            if "python" in shebang:
                python = shebang
    with zipfile.ZipFile(archive) as zf:
        # Ignores __pycache__ since .pyc in __pycache__ aren't executable
        # without the .py.
        MAIN = "__main__"
        main_exists = any(xar_util.file_in_zip(zf, MAIN + ext) for ext in PYTHON_EXTS)
        if main_exists:
            return (python, MAIN)
        return (python, None)


def get_pyc_file(py_file):
    """Returns the .pyc file for `py_file` (not .pyo)."""
    return cache_from_source(py_file, debug_override=True)


def compile_files(py_files):
    """
    Compiles every Python file in `py_files` into a pyc file.
    The pyc file name is determined by `get_pyc_file(py_file)`.
    Returns a dict of files that errored to the error message.
    Note: Always writes to .pyc, even if optimization is enabled.
    """
    errors = {}
    for py_file in py_files:
        pyc_file = get_pyc_file(py_file)
        try:
            py_compile.compile(py_file, pyc_file, doraise=True)
            assert os.path.exists(pyc_file)
            newtime = xar_util.extract_pyc_timestamp(pyc_file)
            os.utime(py_file, (newtime, newtime))
        except py_compile.PyCompileError as e:
            errors[py_file] = e.msg
    return errors


def is_python_version(interpreter, version_info):
    """
    Returns `True` if `interpreter` is version `version_info`.
    """
    VERSION_INFO_MAIN = """
import sys
print('.'.join(str(x) for x in sys.version_info))
    """
    assert interpreter is not None
    with tempfile.NamedTemporaryFile("w+t", delete=False) as f:
        f.write(VERSION_INFO_MAIN)
        f.flush()
        this_version = ".".join(str(x) for x in version_info)
        binary = shlex.split(interpreter)
        output = subprocess.check_output(binary + [f.name])
        other_version = output.decode("utf-8").strip()
        return this_version == other_version


# Cribbed from PythonIdentity.hashbang() in PEX.
def environment_python_interpreter():
    """
    Returns an Python interpreter found in the enviornment that is compatible
    with the currently running Python interpreter.
    """
    ENV_PYTHON = {
        "CPython": "python%(major)d.%(minor)d",
        "Jython": "jython",
        "PyPy": "pypy",
        "IronPython": "ipy",
    }
    python = ENV_PYTHON[platform.python_implementation()] % {
        "major": sys.version_info[0],
        "minor": sys.version_info[1],
        "patch": sys.version_info[2],
    }
    return "/usr/bin/env %s" % python


class WheelMetadata(pkg_resources.EggMetadata):
    """Metadata provider for zipped wheels."""

    def _setup_prefix(self):
        # Cribbed from pkg_resources.EggProvider and pex WheelMetadata.
        for path in xar_util.yield_prefixes_reverse(self.module_path):
            if Wheel.is_wheel_archive(path):
                self.egg_name = os.path.basename(path)
                wf = install.WheelFile(path)
                self.egg_info = os.path.join(path, wf.distinfo_name)
                self.egg_root = path
                break


def does_sha256_match(file, expected_hash):
    """
    Does `file`'s sha256 match `expected_hash`. The `expected_hash` is expected
    to be in the format of RECORD files: sha256=urlsafe_b64_with_no_trailing_==.
    """
    h = hashlib.sha256()
    with open(file, "rb") as f:
        data = f.read(4096)
        while data:
            h.update(data)
            data = f.read(4096)
    hash = b"sha256=" + base64.urlsafe_b64encode(h.digest()).rstrip(b"=")
    return native(hash) == expected_hash


class Wheel(object):
    """
    Wrapper around a pkg_resources.DistInfoDistribution with Wheel specific
    helpers.
    """

    class Error(Exception):
        pass

    WHEEL_INFO = install.WheelFile.WHEEL_INFO
    RECORD = install.WheelFile.RECORD

    # The latest wheel no longer accepts "package-version.dist-info".
    # Copy the old regex here.
    # See https://github.com/pypa/wheel/issues/236
    WHEEL_INFO_RE = re.compile(
        r"""^(?P<namever>(?P<name>.+?)(-(?P<ver>\d.*?))?)
        ((-(?P<build>\d.*?))?-(?P<pyver>.+?)-(?P<abi>.+?)-(?P<plat>.+?)
        \.whl|\.dist-info)$""",
        re.VERBOSE,
    ).match

    @classmethod
    def is_wheel_archive(cls, path):
        """Returns True if `path` is a wheel."""
        return path.lower().endswith(".whl")

    def __init__(self, distribution=None, location=None, importer=None):
        """
        Constructs the WheelDistribution
        """
        if distribution is not None and location is not None:
            raise self.Error("location and distribution cannot both be set")

        if distribution is not None:
            self.distribution = distribution
        else:
            # Construct the metadata provider
            if self.is_wheel_archive(location):
                importer = importer or zipimport.zipimporter(location)
                metadata = WheelMetadata(importer)
            else:
                root = os.path.dirname(location)
                metadata = pkg_resources.PathMetadata(root, location)
            project_name, version, py_version, platform = [None] * 4
            match = self.WHEEL_INFO_RE(os.path.basename(metadata.egg_info))
            if match:
                project_name, version, py_version, platform = match.group(
                    "name", "ver", "pyver", "plat"
                )
                py_version = py_version or sys.version_info[0]
            self.distribution = pkg_resources.DistInfoDistribution(
                location,
                metadata,
                project_name=project_name,
                version=version,
                py_version=py_version,
                platform=platform,
            )
        # self.distribution.egg_info is the only reliable way to get the name.
        # I'm not sure if egg_info is a public interface, but we already rely
        # on it for WheelMetadata.
        wheel_info = os.path.basename(self.distribution.egg_info)
        parsed_filename = self.WHEEL_INFO_RE(wheel_info)
        if parsed_filename is None:
            raise self.Error("Bad wheel '%s'" % wheel_info)
        self.name, self.ver, self.namever = parsed_filename.group(
            "name", "ver", "namever"
        )

    def is_purelib(self):
        """Returns True if the Wheel is a purelib."""
        wheel_info = pkginfo.read_pkg_info_bytes(
            self.distribution.get_metadata(self.WHEEL_INFO).encode("utf-8")
        )
        return wheel_info["Root-Is-Purelib"] == "true"

    def records(self):
        """
        Returns an iterator over the records of the Wheel.
        Iterates over triples [filename, hash, size].
        """
        return csv.reader(self.distribution.get_metadata_lines(self.RECORD))

    def distinfo_name(self):
        return "%s.dist-info" % self.namever

    def distinfo_location(self, install_paths):
        """
        Returns the location of the distinfo using the `install_paths`.
        The `Wheel` can be reconstructed from this location.
        """
        if self.is_purelib():
            root = install_paths["purelib"]
        else:
            root = install_paths["platlib"]
        return os.path.join(root, self.distinfo_name())

    def sys_install_paths(self):
        """Return the system wheel install locations."""
        sys_paths = paths.get_install_paths(self.name)
        for key in sys_paths:
            sys_paths[key] = os.path.realpath(sys_paths[key])
        return sys_paths

    def install(self, src_paths, dst_paths, force=False):
        """
        Install this Wheel distribution to `dst_paths`.
        Uses either :func:`install_archive` or :func:`copy_installation`.
        """
        if self.is_wheel_archive(self.distribution.location):
            self.install_archive(dst_paths, force)
        else:
            self.copy_installation(src_paths, dst_paths, force)

    def install_archive(self, dst_paths, force=False):
        """
        Install a Wheel archive to `dst_paths`.
        """
        if not self.is_wheel_archive(self.distribution.location):
            raise self.Error("install() only works with archives")
        wf = install.WheelFile(self.distribution.location)
        # TODO: The next version of wheel doesn't provide WheelFile,
        # so we will need to have our own implementation of wf.install().
        # When you fix that, please make force=False allow overwrites if the
        # hashes match. You can use does_sha256_match().
        wf.install(overrides=dst_paths, force=True)

    def _determine_kind(self, src_root, src_paths, dst_paths, src_record):
        """
        Determine the most specific `src_paths` kind that the `src_record` is
        located under. If the most specific kind has the same `src_paths[kind]`
        as another kind, then the `dst_paths` must be the same as well.
        """
        kinds = []
        for prefix in xar_util.yield_prefixes_reverse(src_record):
            if prefix in src_paths.values():
                kinds = [kind for kind, path in src_paths.items() if prefix == path]
                break
        else:
            # We were unable to determine the kind, fall back to a heuristic.
            # * If the path contains "/lib/" it is a {pure,plat}lib.
            # * If the path contains "/bin/" it is a script.
            # * If the path contains the name and "include" it is a header.
            # * If the src_root ends with "site-pacakges", the data may be in
            #   "src_root/../../..".
            # This is necessary for Python installed with Homebrew on OS X.
            data = None
            if src_root.endswith("site-packages"):
                data = os.path.normpath(os.path.join(src_root, "../../.."))
            for prefix in xar_util.yield_prefixes_reverse(src_record):
                if prefix.endswith("site-packages"):
                    assert dst_paths["purelib"] == dst_paths["platlib"]
                    return "purelib", prefix
                if prefix.endswith("bin"):
                    return "scripts", prefix
                if prefix.endswith(self.name) and "include" in prefix:
                    return "headers", prefix
                if data and prefix == data:
                    return "data", prefix
        # We must have exactly one unique prefix
        xar_prefix = [dst_paths[kind] for kind in kinds]
        if not kinds or not all(p == xar_prefix[0] for p in xar_prefix):
            raise self.Error(
                "Distribution '%s' has record '%s' with ambiguous kind."
                % (self.namever, src_record)
            )
        kind = kinds[0]
        return kind, src_paths[kind]

    def copy_installation(self, src_paths, dst_paths, force=False):
        """
        Copies an installation of this Wheel in `src_paths` to `dst_paths`.
        Takes care to fix up the 'RECORD' file to reflect the new installtion
        location.
        """
        if self.is_wheel_archive(self.distribution.location):
            raise self.Error("copy_installation() does not work with archives")
        # Determine the src and dst roots.
        if self.is_purelib():
            src_root = src_paths["purelib"]
            dst_root = dst_paths["purelib"]
        else:
            src_root = src_paths["platlib"]
            dst_root = dst_paths["platlib"]
        assert src_root[:1] == os.sep and dst_root[:1] == os.sep
        # Create or overwrite the dst RECORD file.
        dst_records_path = os.path.join(dst_root, self.distinfo_name(), self.RECORD)
        if os.path.exists(dst_records_path) and not force:
            raise self.Error("'RECORD' already exists: '%s'" % self.name)
        xar_util.safe_mkdir(os.path.dirname(dst_records_path))
        with open(dst_records_path, mode="w+t") as f:
            # Loop over each record in the source distribution.
            dst_records = csv.writer(f)
            for record, record_hash, record_size in self.records():
                # Get the normalized absolute path for the source record
                src_record = os.path.normpath(os.path.join(src_root, record))
                # Determine what 'kind' the record is, and get dst_record path.
                kind, prefix = self._determine_kind(
                    src_root, src_paths, dst_paths, src_record
                )
                rel_record = src_record[len(prefix) + 1 :]
                dst_record = os.path.join(dst_paths[kind], rel_record)
                # Update the destination RECORD file.
                new_record = os.path.relpath(dst_record, dst_root)
                dst_records.writerow((new_record, record_hash, record_size))
                # Don't write the records file, since we are recreating it.
                if dst_record == dst_records_path:
                    continue
                # Copy or overwrite the record
                if os.path.exists(dst_record) and not force:
                    if not does_sha256_match(dst_record, record_hash):
                        raise self.Error("'%s' already exists" % dst_record)
                xar_util.safe_mkdir(os.path.dirname(dst_record))
                shutil.copy2(src_record, dst_record)

    def fixup(self, install_paths):
        """
        Deletes .pyc files if the .py file exists (to be recompiled).
        Compiles all Python sources.
        """
        root = os.path.dirname(self.distinfo_location(install_paths))
        # Read the RECORDS
        records = list(self.records())
        # Get a list of Python files (and a set for quick membership tests)
        py_files = [
            os.path.normpath(os.path.join(root, record))
            for record, _, _ in records
            if record.endswith(".py")
        ]
        py_set = set(py_files)
        # Write the new RECORDS file, excluding .pyc files
        new_records = []
        for record_line in records:
            record, _, _ = record_line
            # Add non-pyc files and continue
            is_py = record.endswith(".py")
            if is_py or not any(record.endswith(e) for e in PYTHON_EXTS):
                new_records.append(record_line)
                continue
            # We have a pyc file, delete it if the .py file exists.
            pyc_file = os.path.normpath(os.path.join(root, record))
            try:
                py_file = source_from_cache(pyc_file)
                if py_file in py_set:
                    xar_util.safe_remove(pyc_file)
                    continue
            except ValueError:
                pass
            # There is no .py file, add the .pyc file
            new_records.append(record_line)
        # Compile all the py files
        # Failures are okay since there might be for example Python 3 only code
        errors = compile_files(py_files)
        for _, msg in errors.items():
            logger.warning(msg)
        # Add the new .pyc files relative to root
        new_records += [
            [os.path.relpath(get_pyc_file(f), root), "", ""]
            for f in py_files
            if f not in errors
        ]
        # Write the new RECORDS file
        records_path = os.path.join(root, self.distinfo_name(), self.RECORD)
        with open(records_path, "wt") as f:
            writer = csv.writer(f)
            writer.writerows(new_records)
