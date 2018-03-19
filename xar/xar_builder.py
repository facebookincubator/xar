from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import shutil
import tempfile
import time

from xar import bootstrap_py
from xar import xar_util


BORING_SHEBANG = "#!/bin/echo This is not an executable XAR file."
MAX_SHEBANG = 128  # from linux/include/linux/binfmts.h's BINPRM_BUF_SIZE


class XarBuilder(object):
    """
    Handles the construction of a XAR.
    Files and directories can be added to the XAR until it is frozen, then it
    cannot be modified, and can only be built with XarBuilder.build().
    """
    class Error(Exception): pass
    class InvalidExecutableError(Error): pass
    class FrozenError(Error): pass
    class InvalidShebangError(Error): pass

    def __init__(self, xar_exec=None, mount_root=None, staging_dir=None):
        """Constructs a XarBuilder."""
        self._staging = xar_util.StagingDirectory(staging_dir)
        self._frozen = False

        self._mount_root = mount_root
        self._xar_exec = xar_exec
        if self._xar_exec is None:
            self._xar_exec = "/usr/bin/env xarexec"

        self._executable = None
        self._shebang = None
        self._priorities = None
        self._partition = None

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
        Adds :filename: to the XAR with the xar filename :xar_filename:, which
        does not have to match. If :xar_filename: is None, then the basename of
        :filename: is used. Throws if the file already exists.
        """
        self._ensure_unfrozen()
        if xar_filename is None:
            xar_filename = os.path.basename(filename)
        self._staging.copy(filename, xar_filename)

    def add_directory(self, directory, xar_directory=None):
        """
        Adds :directory: to the XAR with the xar directory name :xar_directory:,
        which does not have to match. If :xar_directory: is None, then the
        root of the xar is set to the directory. Throws if the directory already
        exists.
        """
        self._ensure_unfrozen()
        self._staging.copytree(directory, xar_directory)

    def add_zipfile(self, zf, dst=None):
        """
        Adds a zipfile to the XAR under the :xar_directory:. If :xar_directory:
        is None, then the root of the xar is set to the directory. Throws if the
        directory already exists.
        """
        self._ensure_unfrozen()
        self._staging.extract(zf, dst)

    def _set_shebang(self, shebang):
        """Sets the shebang."""
        self._ensure_unfrozen()
        if self._shebang is not None:
            raise self.InvalidShebangError("Already have a shebang")
        if not shebang.startswith('#!'):
            raise self.InvalidShebangError("Invalid shebang '%s'" % shebang)
        if len(shebang) > MAX_SHEBANG:
            raise self.InvalidShebangError("Shebang too long '%s'" % shebang)
        self._shebang = shebang

    def set_executable(self, xar_filename):
        """
        Sets the executable to the relative path :xar_filename:, which must
        already be present in the XAR.
        """
        self._ensure_unfrozen()
        if self._executable is not None:
            raise self.InvalidExecutableError("Already have an executable")
        if not self._staging.exists(xar_filename):
            raise self.InvalidExecutableError("Executable '%s' does not exist"
                                              % xar_filename)
        self._set_shebang("#!%s" % self._xar_exec)
        self._executable = xar_filename

    def add_executable(self, filename, xar_filename=None):
        """Calls add_file() and then set_executable()."""
        if xar_filename is None:
            xar_filename = os.path.basename(filename)
        self.add_file(filename, xar_filename)
        self.set_executable(xar_filename)

    def sort_by_extension(self, priorities, override=False):
        """
        Sets the sort priorities for mksquashfs. :priorities: is a list of file
        extensions. Files are sorted in the order that their extensions appear
        in :priorities:. This may be called before adding all the files, since
        the work will only happen once the XarBuilder is frozen. Refuses to
        override existing priorities unless :override: is True.
        """
        self._ensure_unfrozen()
        if not override and self._priorities is not None:
            raise self.Error("Refusing to override existing sort priorities")
        self._priorities = priorities

    def _run_sort_by_extension(self):
        """Performs the sort_by_extension() work once frozen."""
        self._ensure_frozen()
        self._sort_file = None
        if self._priorities is None:
            return
        with tempfile.NamedTemporaryFile(mode="w+t", delete=False) as f:
            xar_util.write_sort_file(self._staging.path(), self._priorities, f)
            self._sort_file = f.name

    def partition_by_extension(self, partition, override=False):
        """
        Partitions the files into separate XARs based on their extension.
        :partition: is a list of extensions which go into their own XARs.
        The partitioned XARs are added as dependencies to the main XAR.
        This may be called before adding all the files, since the work will only
        happen once the XarBuilder is frozen. Refuses to override existing
        partition unless :override: is True.
        """
        self._ensure_unfrozen()
        if not override and self._partition is not None:
            raise self.Error("Refusing to override existing ext. partition")
        self._partition = partition

    def _run_partition_by_extension(self):
        """Performs the partition_by_extension() work once frozen."""
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
        """Freezes the XarBuilder."""
        self._ensure_unfrozen()
        if self._shebang is None:
            self._set_shebang(BORING_SHEBANG)
        self._frozen = True
        self._version = int(time.time())
        self._run_sort_by_extension()
        self._run_partition_by_extension()

    def delete(self):
        """Delete temporary resources."""
        self._staging.delete()
        if self._sort_file is not None:
            xar_util.safe_remove(self._sort_file)
        for dest in self._partition_dest.values():
            dest.staging.delete()

    def _build_staging_dir(self, staging_dir, filename, shebang,
                           xar_header, squashfs_options):
        """Builds a single XAR for the given :staging_dir:."""
        self._ensure_frozen()
        os.chmod(staging_dir.path(), 0o755)
        xar = xar_util.XarFactory(staging_dir.path(), filename, shebang)
        if xar_header is not None:
            xar.xar_header = xar_header.copy()
        xar.version = self._version
        xar.version = self._version
        xar.sort_file = self._sort_file
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
        Writes the XAR to :filename:. Uses :squashfs_options: to construct the
        XAR.
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
            self._build_staging_dir(destination.staging, xarfiles[ext][1],
                                    BORING_SHEBANG, {}, squashfs_options)
        # Build the main XAR
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tmp_xar = tf.name
        xar_header = self._build_xar_header(xarfiles)
        self._build_staging_dir(self._staging, tmp_xar, self._shebang,
                                xar_header, squashfs_options)

        # Move the results into place
        shutil.move(tmp_xar, filename)
        for ext_filename, tmp_filename in xarfiles.values():
            shutil.move(tmp_filename, ext_filename)

        # Make the output executable if necessary
        if self._executable is not None:
            os.chmod(filename, 0o755)

        self.delete()


class PythonXarBuilder(XarBuilder):
    class InvalidEntryPointError(XarBuilder.Error): pass
    class InvalidInterpreterError(XarBuilder.Error): pass

    def __init__(self, *args, **kwargs):
        self._entry_point = None
        self._interpreter = None

        super(PythonXarBuilder, self).__init__(*args, **kwargs)

    def set_entry_point(self, entry_point):
        self._ensure_unfrozen()
        self._validate_entry_point(entry_point)
        if self._entry_point is not None:
            raise self.InvalidEntryPointError("Entry point is already set")
        self._entry_point = entry_point

    def set_interpreter(self, interpreter):
        """Sets the python interpreter to :python:."""
        self._ensure_unfrozen()
        if self._interpreter is not None:
            raise self.InvalidInterpreterError("Interpreter is already set")
        self._interpreter = interpreter

    def _validate_entry_point(self, entry_point):
        def ensure_exists(module):
            basename = os.sep.join(module.split('.'))
            for ext in xar_util.PYTHON_EXTS:
                if self._staging.exists(basename + ext):
                    return
            raise self.InvalidEntryPointError("Module '%s' not found in XAR"
                                              % module)

        module, function = xar_util.parse_entry_point(entry_point)
        ensure_exists(module)

        parent_end = module.rfind(".")
        while parent_end > 0:
            parent_module = module[:parent_end]
            ensure_exists(parent_module + ".__init__")
            parent_end = parent_module.rfind(".")

    def _bootstrap(self):
        """Set up the Python bootstrapping."""
        if self._interpreter is None:
            raise self.InvalidInterpreterError("Interpreter is not set.")
        if self._entry_point is None:
            raise self.InvalidEntryPointError("Entry point is not set")
        module, function = xar_util.parse_entry_point(self._entry_point)
        fmt_args = {
            "python": self._interpreter,
            "module": module,
            "run_xar_main": bootstrap_py.RUN_XAR_MAIN,
        }
        if function is not None:
            fmt_args["function"] = function
        bootstrap_xar = bootstrap_py.BOOTSTRAP_XAR_TEMPLATE.format(**fmt_args)
        run_xar_main = bootstrap_py.run_xar_main(**fmt_args)

        self._staging.write(bootstrap_xar, bootstrap_py.BOOTSTRAP_XAR,
                            mode="w", permissions=0o755)
        self._staging.write(run_xar_main, bootstrap_py.RUN_XAR_MAIN,
                            mode="w", permissions=0o644)
        self.set_executable(bootstrap_py.BOOTSTRAP_XAR)

    def freeze(self):
        self._bootstrap()
        super(PythonXarBuilder, self).freeze()
