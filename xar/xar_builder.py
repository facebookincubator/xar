# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil
import sys
import tempfile
import time

from xar import bootstrap_py, py_util, xar_util


BORING_SHEBANG = "#!/bin/echo This is not an executable XAR file."
MAX_SHEBANG = 128  # from linux/include/linux/binfmts.h's BINPRM_BUF_SIZE


class XarBuilder(object):
    """
    Handles the construction of a XAR.
    Files and directories can be added to the XAR until it is frozen, then it
    cannot be modified, and can only be built with XarBuilder.build().
    """

    class Error(Exception):
        pass

    class InvalidExecutableError(Error):
        pass

    class FrozenError(Error):
        pass

    class InvalidShebangError(Error):
        pass

    def __init__(self, xar_exec=None, mount_root=None):
        """
        Constructs a XarBuilder given the optional `xar_exec` path and
        `mount_root`. `xar_exec` is the executable that runs the xar and
        `mount_root` is where `xar_exec` will mount the squashfs filesystem.
        """
        self._staging = xar_util.StagingDirectory()
        self._frozen = False

        self._mount_root = mount_root
        self._xar_exec = xar_exec
        if self._xar_exec is None:
            self._xar_exec = "/usr/bin/env xarexec_fuse"

        self._executable = None
        self._shebang = None
        self._priorities = None
        self._partition = None

        self._version = None
        self._sort_file = None
        self._partition_dest = {}

    def _ensure_frozen(self):
        if not self._frozen:
            raise self.FrozenError("Expected to be frozen")

    def _ensure_unfrozen(self):
        if self._frozen:
            raise self.FrozenError("Expected not to be frozen")

    def add_file(self, filename, xar_filename=None):
        """
        Adds `filename` to the XAR with the xar filename `xar_filename`, which
        does not have to match. If `xar_filename` is `None`, then the basename
        of `filename` is used. Throws if the file already exists.
        """
        self._ensure_unfrozen()
        if xar_filename is None:
            xar_filename = os.path.basename(filename)
        self._staging.copy(filename, xar_filename)

    def add_directory(self, directory, xar_directory=None):
        """
        Adds `directory` to the XAR with the xar directory name `xar_directory`,
        which does not have to match. If `xar_directory` is `None`, then the
        root of the xar is set to the directory. Throws if the directory already
        exists.
        """
        self._ensure_unfrozen()
        self._staging.copytree(directory, xar_directory)

    def add_zipfile(self, zf, dst=None):
        """
        Adds a zipfile to the XAR under `dst`. If `dst` is `None`, then the root
        of the xar is set to the directory. Throws if any extracted file already
        exists.
        """
        self._ensure_unfrozen()
        self._staging.extract(zf, dst)

    def _set_shebang(self, shebang):
        """Sets the shebang."""
        self._ensure_unfrozen()
        if self._shebang is not None:
            raise self.InvalidShebangError("Already have a shebang")
        if not shebang.startswith("#!"):
            raise self.InvalidShebangError("Invalid shebang '%s'" % shebang)
        if len(shebang) > MAX_SHEBANG:
            raise self.InvalidShebangError("Shebang too long '%s'" % shebang)
        self._shebang = shebang

    def set_executable(self, xar_filename):
        """
        Sets the executable to the relative path `xar_filename`, which must
        already be present in the XAR. `xar_exec` will execute this file when
        the XAR is executed.
        """
        self._ensure_unfrozen()
        if self._executable is not None:
            raise self.InvalidExecutableError("Already have an executable")
        if not self._staging.exists(xar_filename):
            raise self.InvalidExecutableError(
                "Executable '%s' does not exist" % xar_filename
            )
        self._set_shebang("#!%s" % self._xar_exec)
        self._executable = xar_filename

    def add_executable(self, filename, xar_filename=None):
        """Calls :func:`add_file` and then :func:`set_executable`."""
        if xar_filename is None:
            xar_filename = os.path.basename(filename)
        self.add_file(filename, xar_filename)
        self.set_executable(xar_filename)

    def sort_by_extension(self, priorities, override=False):
        """
        Sets the sort priorities for mksquashfs. `priorities` is a list of file
        extensions. Files are sorted in the order that their extensions appear
        in `priorities`. This may be called before adding all the files, since
        the work will only happen once the XarBuilder is frozen. Refuses to
        override existing priorities unless `override` is `True`.
        """
        self._ensure_unfrozen()
        if not override and self._priorities is not None:
            raise self.Error("Refusing to override existing sort priorities")
        self._priorities = priorities

    def _run_sort_by_extension(self):
        """Performs the :func:`sort_by_extension` work once frozen."""
        self._ensure_frozen()
        self._sort_file = None
        if self._priorities is None:
            return
        self._sort_file = xar_util.TemporaryFile()
        with self._sort_file.open(mode="w+t") as f:
            xar_util.write_sort_file(self._staging.path(), self._priorities, f)

    def partition_by_extension(self, partition, override=False):
        """
        Partitions the files into separate XARs based on their extension.
        `partition` is a list of extensions which go into their own XARs.
        The partitioned XARs are added as dependencies to the main XAR.
        This may be called before adding all the files, since the work will only
        happen once the XarBuilder is frozen. Refuses to override existing
        partition unless `override` is True.
        """
        self._ensure_unfrozen()
        if not override and self._partition is not None:
            raise self.Error("Refusing to override existing ext. partition")
        self._partition = partition

    def _run_partition_by_extension(self):
        """Performs the :func:`partition_by_extension` work once frozen."""
        self._ensure_frozen()
        self._partition_dest = {}
        if self._partition is None:
            return
        for ext in self._partition:
            staging_dir = xar_util.StagingDirectory()
            uuid = xar_util.make_uuid()
            dest = xar_util.PartitionDestination(staging_dir, uuid)
            self._partition_dest["." + ext.lstrip(".")] = dest
        xar_util.partition_files(self._staging, self._partition_dest)

    def freeze(self):
        """
        Freezes the XarBuilder. After this point the XarBuilder may not be
        modified, and the only valid operations are :func:`build` and
        :func:`delete`.
        """
        self._ensure_unfrozen()
        if self._shebang is None:
            self._set_shebang(BORING_SHEBANG)
        self._frozen = True
        self._version = int(time.time())
        self._run_sort_by_extension()
        self._run_partition_by_extension()

    def delete(self):
        """
        Delete temporary resources. Only necessary if :func:`build` is never
        called. The XarBuilder is no longer usable after this call.
        """
        self._staging.delete()
        if self._sort_file is not None:
            self._sort_file.delete()
        for dest in self._partition_dest.values():
            dest.staging.delete()

    def _build_staging_dir(
        self, staging_dir, filename, shebang, xar_header, squashfs_options
    ):
        """Builds a single XAR."""
        self._ensure_frozen()
        os.chmod(staging_dir.path(), 0o755)
        xar = xar_util.XarFactory(staging_dir.path(), filename, shebang)
        if xar_header is not None:
            xar.xar_header = xar_header.copy()
        xar.version = self._version
        xar.version = self._version
        if self._sort_file:
            xar.sort_file = self._sort_file.name()
        xar.squashfs_options = squashfs_options
        xar.go()

    def _build_xar_header(self, xar_dependencies):
        """Make the XAR headers."""
        self._ensure_frozen()
        xar_header = {}
        xar_header["DEPENDENCIES"] = " ".join(
            [os.path.basename(v[0]) for v in xar_dependencies]
        )
        if self._mount_root:
            xar_header["MOUNT_ROOT"] = self._mount_root
        if self._executable is not None:
            xar_header["XAREXEC_TARGET"] = self._executable
        return xar_header

    def build(self, filename, squashfs_options=None):
        """
        Actually build the XAR. Freezes the XarBuilder if not already frozen.
        Writes the XAR to `filename`. Uses `xar_util.SquashfsOptions`
        `squashfs_options` to construct the XAR. Finally calls :func:`delete`.
        The XarBuilder is no longer usable after this call.
        """
        if squashfs_options is None:
            squashfs_options = xar_util.SquashfsOptions()
        if not self._frozen:
            self.freeze()
        xarfiles = {}
        base_name, xar_ext = os.path.splitext(filename)
        # Build the dependent XARs
        for ext, destination in self._partition_dest:
            ext_filename = base_name + ext + xar_ext
            with tempfile.NamedTemporaryFile(delete=False) as tf:
                xarfiles[ext] = (ext_filename, tf.name)
            self._build_staging_dir(
                destination.staging,
                xarfiles[ext][1],
                BORING_SHEBANG,
                {},
                squashfs_options,
            )
        # Build the main XAR
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tmp_xar = tf.name
        xar_header = self._build_xar_header(xarfiles)
        self._build_staging_dir(
            self._staging, tmp_xar, self._shebang, xar_header, squashfs_options
        )

        # Move the results into place
        shutil.move(tmp_xar, filename)
        for ext_filename, tmp_filename in xarfiles.values():
            shutil.move(tmp_filename, ext_filename)

        # Make the output executable if necessary
        if self._executable is not None:
            os.chmod(filename, 0o755)

        self.delete()


class PythonXarBuilder(XarBuilder):
    """
    Handles the construction of a Python executable XAR.
    All of the Python dependencies should be bundled into the XAR, since the XAR
    will set the `$PYTHONPATH` to be the mounted squash filesystem during the
    bootstrap phase. The invoked executable name is stored in the environment
    variable `$XAR_INVOKED_NAME` and the mounted XAR squashfs filesystem root is
    stored in the environment variable `$XAR_RUNTIME_FILES`. Extra dependencies
    can be added with the XarBuilder methods. The XAR will execute the given
    Python entry point with the given Python interpreter.
    """

    class InvalidEntryPointError(XarBuilder.Error):
        pass

    class InvalidInterpreterError(XarBuilder.Error):
        pass

    class InvalidDistributionError(XarBuilder.Error):
        pass

    LIBRARY_PATH = ""

    def __init__(self, *args, **kwargs):
        self._entry_point = None
        self._interpreter = None
        self._distributions = set()

        super(PythonXarBuilder, self).__init__(*args, **kwargs)

    def _validate_entry_point(self, entry_point):
        """Validates that the module specified in `entry_point` exists."""

        def ensure_exists(module):
            basename = os.path.join(self.LIBRARY_PATH, *module.split("."))
            if os.path.isdir(self._staging.absolute(basename)):
                basename = basename + "/__init__"
            for ext in py_util.PYTHON_EXTS:
                if self._staging.exists(basename + ext):
                    return
            raise self.InvalidEntryPointError("Module '%s' not found in XAR" % module)

        module, function = py_util.parse_entry_point(entry_point)

        parent_end = len(module)
        while parent_end > 0:
            parent_module = module[:parent_end]
            ensure_exists(parent_module)
            parent_end = parent_module.rfind(".")

    def set_entry_point(self, entry_point):
        """
        Sets the Python entry point for the XAR. In the format `module:function`
        or `module`. This is what the XAR executes after bootstrapping. Must be
        called before :func:`freeze`.
        """
        self._ensure_unfrozen()
        self._validate_entry_point(entry_point)
        if self._entry_point is not None:
            raise self.InvalidEntryPointError("Entry point is already set")
        self._entry_point = entry_point

    def set_interpreter(self, interpreter):
        """
        Sets the python interpreter to `python`. Defaults to calling
        :func:`py_util.environment_python_interpreter` for the interpreter if
        not set.
        """
        self._ensure_unfrozen()
        if self._interpreter is not None:
            raise self.InvalidInterpreterError("Interpreter is already set")
        if not py_util.is_python_version(interpreter, sys.version_info):
            raise self.InvalidInterpreterError(
                "%s is not compatible with the running Python version." % interpreter
            )
        self._interpreter = interpreter

    def _xar_install_paths(self, dist_name, absolute):
        """Return the XAR wheel install locations."""
        prefix = ""
        if absolute:
            prefix = self._staging.absolute() + os.sep
        return {
            "purelib": "%s%s" % (prefix, self.LIBRARY_PATH),
            "platlib": "%s%s" % (prefix, self.LIBRARY_PATH),
            "headers": "%sinclude/%s" % (prefix, dist_name),
            "scripts": "%sbin" % prefix,
            "data": prefix,
        }

    def add_distribution(self, distribution):
        """
        Add a `pkg_resources.Distribution` to the XAR. The distribution must be
        a wheel, but it may be either a zipfile or already unpacked.
        Handles all the installation, and adding the distribution to the Python
        path.
        """
        self._ensure_unfrozen()
        # We only support wheels.
        if not distribution.has_metadata(py_util.Wheel.WHEEL_INFO):
            raise self.InvalidDistributionError(
                "'%s' is not a wheel! It might be an egg, try reinstalling as "
                "a wheel." % distribution.project_name
            )
        wheel = py_util.Wheel(distribution=distribution)
        sys_paths = wheel.sys_install_paths()
        xar_paths = self._xar_install_paths(wheel.name, absolute=True)
        wheel.install(sys_paths, xar_paths, force=False)
        self._distributions.add(wheel.distinfo_location(xar_paths))

    def _fixup_distributions(self):
        """Fixup the distributions."""
        for distinfo_location in self._distributions:
            wheel = py_util.Wheel(location=distinfo_location)
            xar_paths = self._xar_install_paths(wheel.name, absolute=True)
            wheel.fixup(xar_paths)

    def _bootstrap(self):
        """Set up the Python bootstrapping."""
        if self._interpreter is None:
            self._interpreter = py_util.environment_python_interpreter()
        if self._entry_point is None:
            raise self.InvalidEntryPointError("Entry point is not set")

        module, function = py_util.parse_entry_point(self._entry_point)
        fmt_args = {
            "python": self._interpreter,
            "module": module,
            "run_xar_main": bootstrap_py.RUN_XAR_MAIN,
        }
        if function is not None:
            fmt_args["function"] = function
        bootstrap_xar = bootstrap_py.BOOTSTRAP_XAR_TEMPLATE.format(**fmt_args)
        run_xar_main = bootstrap_py.run_xar_main(**fmt_args)

        self._staging.write(
            bootstrap_xar, bootstrap_py.BOOTSTRAP_XAR, mode="w", permissions=0o755
        )
        self._staging.write(
            run_xar_main, bootstrap_py.RUN_XAR_MAIN, mode="w", permissions=0o644
        )
        self.set_executable(bootstrap_py.BOOTSTRAP_XAR)

    def freeze(self):
        """
        See :func:`XarBuilder.freeze`. Adds in the extra Python specific steps.
        """
        self._fixup_distributions()
        self._bootstrap()
        super(PythonXarBuilder, self).freeze()
