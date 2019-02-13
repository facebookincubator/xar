# Copyright (c) 2018-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function

import copy
import os
import sys
from distutils import log
from distutils.dir_util import mkpath, remove_tree
from distutils.errors import DistutilsOptionError

import pkg_resources
from setuptools import Command
from xar import finders, pip_installer, py_util, xar_builder, xar_util


class bdist_xar(Command):
    description = "Create a XAR build distribution"

    user_options = [
        (
            "interpreter=",
            None,
            "The Python interpreter to use to run the XAR, which must be the ",
            "same version as sys.executable, default: a Python in the "
            "environment that is compatible with the running interpreter.",
        ),
        (
            "console-scripts=",
            None,
            "A common separated list of 'console_scripts' to build, or 'all'. "
            "Default: build the script with the package name, or if there is "
            "only one console script build that, otherwise fail.",
        ),
        ("download", None, "Download missing dependencies using pip"),
        (
            "xar-exec=",
            None,
            "Path to xarexec, which must be present to run the XAR file, "
            "default: /usr/bin/env xarexec_fuse.",
        ),
        (
            "xar-mount-root=",
            None,
            "Where the XAR file will be mounted by default, default: unset, "
            "will try both /mnt/xarfuse and /dev/shm.",
        ),
        (
            "xar-compression-algorithm=",
            None,
            "Compression algorithm for XAR file, default: gzip.",
        ),
        (
            "xar-block-size=",
            None,
            "Block size used when compressing the XAR file, default: 256K.",
        ),
        (
            "xar-zstd-level=",
            None,
            "Compression level when zstd compression is used, default: 16.",
        ),
        ("bdist-dir=", "b", "directory for building creating the distribution."),
        (
            "dist-dir=",
            "d",
            "directory for building creating the distribution, default: dist.",
        ),
        ("exclude-source-files", None, "remove all .py files from the generated egg"),
        (
            "keep-temp",
            "k",
            "keep the pseudo-installation tree around after "
            "creating the distribution archive",
        ),
        ("skip-build", None, "skip rebuilding everything (for testing/debugging)"),
    ]

    ALL = ["all"]

    boolean_options = ["exclude-source-files", "keep-temp", "skip-build"]

    def initialize_options(self):
        self.bdist_dir = None
        self.dist_dir = None
        self.exclude_source_files = False
        self.keep_temp = False
        self.skip_build = False
        self.console_scripts = None
        self.interpreter = None
        self.download = False
        # XAR options
        self.xar_exec = None
        self.xar_mount_root = None
        self.xar_compression_algorithm = None
        self.xar_block_size = None
        self.xar_zstd_level = None

    def finalize_options(self):
        if self.bdist_dir is None:
            bdist_base = self.get_finalized_command("bdist").bdist_base
            self.bdist_dir = os.path.join(bdist_base, "xar")
        if self.dist_dir is None:
            script_name = os.path.expanduser(self.distribution.script_name)
            package_dir = os.path.dirname(os.path.realpath(script_name))
            self.dist_dir = os.path.join(package_dir, "dist")
        if self.console_scripts is not None:
            self.console_scripts = self.console_scripts.strip().split(",")
        self.sqopts = xar_util.SquashfsOptions()
        if self.xar_compression_algorithm is not None:
            self.sqopts.compression_algorithm = self.xar_compression_algorithm
        else:
            self.sqopts.compression_algorithm = "gzip"
        if self.xar_block_size is not None:
            self.sqopts.block_size = self.xar_block_size
        if self.xar_zstd_level is not None:
            self.sqopts.zstd_level = self.xar_zstd_level
        self.xar_outputs = []

        self.working_set = pkg_resources.WorkingSet(sys.path)
        self.installer = None
        if self.download:
            bdist_pip = os.path.join(self.bdist_dir, "downloads")
            mkpath(bdist_pip)
            self.installer = pip_installer.PipInstaller(
                bdist_pip, self.working_set, log
            )

    def get_outputs(self):
        return self.xar_outputs

    def _add_distribution(self, xar):
        bdist_wheel = self.reinitialize_command("bdist_wheel")
        bdist_wheel.skip_build = self.skip_build
        bdist_wheel.keep_temp = self.keep_temp
        bdist_wheel.bdist_dir = os.path.join(self.bdist_dir, "wheel-bdist")
        bdist_wheel.dist_dir = os.path.join(self.bdist_dir, "wheel-dist")
        bdist_wheel.universal = False
        bdist_wheel.exclude_source_files = self.exclude_source_files
        bdist_wheel.distribution.dist_files = []
        self.run_command("bdist_wheel")
        assert len(bdist_wheel.distribution.dist_files) == 1
        wheel = bdist_wheel.distribution.dist_files[0][2]
        dist = py_util.Wheel(location=wheel).distribution
        xar.add_distribution(dist)
        return dist

    def _parse_console_scripts(self):
        """
        Get a map of console scripts to build based on :self.console_scripts:.
        """
        name = self.distribution.get_name()
        all_console_scripts = []
        entry_points = self.distribution.entry_points
        if entry_points:
            entry_points = pkg_resources.EntryPoint.parse_map(entry_points)
            all_console_scripts = entry_points.get("console_scripts", {})
        if len(all_console_scripts) == 0:
            raise DistutilsOptionError("'%s' has no 'console_scripts'" % name)
        if self.console_scripts == self.ALL:
            return all_console_scripts
        if self.console_scripts is None:
            if len(all_console_scripts) == 1:
                return all_console_scripts
            if name in all_console_scripts:
                return {name: all_console_scripts[name]}
            raise DistutilsOptionError(
                "More than one entry point, set --console-scripts"
            )
        console_scripts = {}
        for script in self.console_scripts:
            if script not in all_console_scripts:
                raise DistutilsOptionError("'%s' is not in 'console_scripts'" % script)
            console_scripts[script] = all_console_scripts[script]
        return console_scripts

    def _set_entry_point(self, xar, entry_point):
        attrs = ".".join(entry_point.attrs)
        entry_point_str = "%s:%s" % (entry_point.module_name, attrs)
        xar.set_entry_point(entry_point_str)

    def _deps(self, dist, extras=()):
        requires = dist.requires(extras=extras)
        try:
            finders.register_finders()
            # Requires setuptools>=34.1 for the bug fix.
            return set(
                self.working_set.resolve(
                    requires, extras=extras, installer=self.installer
                )
            )
        except pkg_resources.DistributionNotFound:
            name = self.distribution.get_name()
            requires_str = "\n\t".join(str(req) for req in requires)
            log.error(
                "%s's requirements are not satisfied:\n\t%s\n"
                "Either pass --download to bdist_xar to download missing "
                "dependencies with pip or try 'pip install /path/to/%s'."
                % (name, requires_str, name)
            )
            raise

    def _build_entry_point(self, base_xar, dist, common_deps, entry_name, entry_point):
        # Clone the base xar
        xar = copy.deepcopy(base_xar)
        # Add in any extra dependencies
        deps = self._deps(dist, entry_point.extras)
        deps -= common_deps
        for dep in deps:
            log.info("adding dependency '%s' to xar" % dep.project_name)
            xar.add_distribution(dep)
        # Set the entry point
        self._set_entry_point(xar, entry_point)
        # Build the XAR
        xar_output = os.path.join(self.dist_dir, entry_name + ".xar")
        mkpath(self.dist_dir)
        log.info("creating xar '%s'" % xar_output)
        xar.build(xar_output, self.sqopts)
        self.xar_outputs.append(xar_output)

    def run(self):
        try:
            xar = xar_builder.PythonXarBuilder(self.xar_exec, self.xar_mount_root)
            # Build an egg for this package and import it.
            dist = self._add_distribution(xar)
            # Add in the dependencies common to each entry_point
            deps = self._deps(dist)
            for dep in deps:
                log.info("adding dependency '%s' to xar" % dep.project_name)
                xar.add_distribution(dep)
            # Set the interpreter to the current python interpreter
            if self.interpreter is not None:
                xar.set_interpreter(self.interpreter)
            # Build a XAR for each entry point specified
            entry_points = self._parse_console_scripts()
            for entry_name, entry_point in entry_points.items():
                self._build_entry_point(xar, dist, deps, entry_name, entry_point)
        finally:
            # Clean up the build directory
            if not self.keep_temp:
                remove_tree(self.bdist_dir)
