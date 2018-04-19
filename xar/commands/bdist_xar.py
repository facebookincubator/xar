from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import copy
import os
import pkg_resources
import sys
import zipimport

from distutils.dir_util import remove_tree, mkpath
from distutils.errors import DistutilsOptionError
from distutils import log
from setuptools import Command

from xar import py_util, xar_builder


class bdist_xar(Command):
    description = "Create a XAR build distribution"

    user_options = [
        (
            "interpreter=", None,
            "The Python interpreter to use to run the XAR, which must be the ",
            "same version as sys.executable, default: sys.executable.",
        ),
        (
            "console-scripts=", None,
            "A common separated list of 'console_scripts' to build, or 'all'. "
            "Default: build the script with the package name, or if there is "
            "only one console script build that, otherwise fail."
        ),
        (
            'bdist-dir=', 'b',
            "directory for building creating the distribution."
        ),
        (
            'dist-dir=', 'd',
            "directory for building creating the distribution, default: dist."
        ),
        (
            'exclude-source-files', None,
            "remove all .py files from the generated egg"
        ),
        (
            'keep-temp', 'k',
            "keep the pseudo-installation tree around after "
            "creating the distribution archive"
        ),
        (
            "skip-build", None,
            "skip rebuilding everything (for testing/debugging)"
        ),
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

    def finalize_options(self):
        if self.bdist_dir is None:
            bdist_base = self.get_finalized_command('bdist').bdist_base
            self.bdist_dir = os.path.join(bdist_base, 'xar')
        if self.dist_dir is None:
            script_name = os.path.expanduser(self.distribution.script_name)
            package_dir = os.path.dirname(os.path.realpath(script_name))
            self.dist_dir = os.path.join(package_dir, 'dist')
        if self.console_scripts is not None:
            self.console_scripts = self.console_scripts.strip().split(',')
        if self.interpreter is None:
            self.interpreter = sys.executable
        self.xar_outputs = []

    def get_outputs(self):
        return self.xar_outputs

    def _distribution_from_wheel(self, wheel):
        importer = zipimport.zipimporter(wheel)
        metadata = py_util.WheelMetadata(importer)
        dist = pkg_resources.DistInfoDistribution.from_filename(
            wheel, metadata=metadata)
        return dist

    def _add_distribution(self, xar):
        bdist_wheel = self.reinitialize_command('bdist_wheel')
        bdist_wheel.skip_build = self.skip_build
        bdist_wheel.keep_temp = self.keep_temp
        bdist_wheel.bdist_dir = os.path.join(self.bdist_dir, "wheel-bdist")
        bdist_wheel.dist_dir = os.path.join(self.bdist_dir, "wheel-dist")
        bdist_wheel.universal = False
        bdist_wheel.exclude_source_files = self.exclude_source_files
        bdist_wheel.distribution.dist_files = []
        self.run_command('bdist_wheel')
        assert len(bdist_wheel.distribution.dist_files) == 1
        wheel = bdist_wheel.distribution.dist_files[0][2]
        dist = self._distribution_from_wheel(wheel)
        xar.add_distribution(dist)
        return dist

    def _parse_console_scripts(self):
        """
        Get a map of console scripts to build based on :self.console_scripts:.
        """
        name = self.distribution.get_name()
        entry_points = self.distribution.entry_points
        entry_points = pkg_resources.EntryPoint.parse_map(entry_points)
        all_console_scripts = entry_points.get('console_scripts', {})
        if len(all_console_scripts) == 0:
            raise DistutilsOptionError("'%s' has no 'console_scripts'" % name)
        if self.console_scripts == self.ALL:
            return all_console_scripts
        if self.console_scripts is None:
            if len(all_console_scripts) == 1:
                return all_console_scripts
            if name in all_console_scripts:
                return {name: self.console_scripts[name]}
            raise DistutilsOptionError(
                "More than one entry point, set --console-scripts")
        console_scripts = {}
        for script in self.console_scripts:
            if script not in all_console_scripts:
                raise DistutilsOptionError("'%s' is not in 'console_scripts'"
                                           % script)
            console_scripts[script] = all_console_scripts[script]
        return console_scripts

    def _set_entry_point(self, xar, entry_point):
        attrs = ".".join(entry_point.attrs)
        entry_point_str = "%s:%s" % (entry_point.module_name, attrs)
        xar.set_entry_point(entry_point_str)

    def _add_dependencies(self, xar, dist, entry_point=None):
        # The entry point may require extra dependencies
        extras = entry_point.extras if entry_point else ()
        # Add in the dependencies
        deps = pkg_resources.working_set.resolve(dist.requires(extras=extras))
        for dep in deps:
            xar.add_distribution(dep)
        return set(deps)

    def _build_entry_point(self, base_xar, dist, common_deps, entry_name,
                           entry_point):
        # Clone the base xar
        xar = copy.deepcopy(base_xar)
        # Add in any extra dependencies
        extras = entry_point.extras
        requires = dist.requires(extras=extras)
        # Requires setuptools>=34.1 for the bug fix.
        deps = set(pkg_resources.working_set.resolve(requires, extras=extras))
        deps -= common_deps
        for dep in deps:
            xar.add_distribution(dep)
        # Set the entry point
        self._set_entry_point(xar, entry_point)
        # Build the XAR
        xar_output = os.path.join(self.dist_dir, entry_name + ".xar")
        mkpath(self.dist_dir)
        log.info("creating xar '%s'" % xar_output)
        xar.build(xar_output)
        self.xar_outputs.append(xar_output)

    def run(self):
        try:
            xar = xar_builder.PythonXarBuilder()
            # Build an egg for this package and import it.
            dist = self._add_distribution(xar)
            # Add in the dependencies common to each entry_point
            deps = set(pkg_resources.working_set.resolve(dist.requires()))
            for dep in deps:
                xar.add_distribution(dep)
            # Set the interpreter to the current python interpreter
            xar.set_interpreter(self.interpreter)
            # Build a XAR for each entry point specified
            entry_points = self._parse_console_scripts()
            for entry_name, entry_point in entry_points.items():
                self._build_entry_point(xar, dist, deps, entry_name,
                                        entry_point)
        finally:
            # Clean up the build directory
            if not self.keep_temp:
                remove_tree(self.bdist_dir)
