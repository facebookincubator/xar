# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function

import contextlib
import multiprocessing
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile

import pkg_resources
from xar import finders, py_util, xar_util


class PipException(Exception):
    pass


class BuildException(Exception):
    pass


class PipInstaller(object):
    """
    Installer function object for pkg_resources.working_set.resolve().
    It is called like `installer(requirement)` when the requirement can't be
    found in the working set. See `__call__()` for documentation.
    """

    def __init__(self, dest, working_set, log=None):
        """
        Download Wheels to `dest` and add them to the `working_set`.
        """
        self._dest = dest
        self._working_set = working_set
        self._log = log
        self._working_set.add_entry(self._dest)
        req = pkg_resources.Requirement.parse("pip")
        dist = self._working_set.find(req)
        self._pip_main = pkg_resources.load_entry_point(dist, "console_scripts", "pip")

    def clean(self):
        """
        Remove any non-wheels from the downloads directory.
        """
        for entry in os.listdir(self._dest):
            if not py_util.Wheel.is_wheel_archive(entry):
                xar_util.safe_remove(os.path.join(self._dest, entry))

    def invoke_pip(self, args):
        def main(args):
            sys.exit(self._pip_main(args))

        p = multiprocessing.Process(target=main, args=(args,))
        p.start()
        p.join()
        if p.exitcode == 0:
            return
        raise PipException("'pip %s' failed" % " ".join(args))

    def download(self, requirement):
        """
        Download the requirement to the downloads directory using pip.
        """
        args = ["download", "-d", self._dest, str(requirement)]
        self.invoke_pip(args)

    def extract_sdist(self, sdist, dest):
        """
        Extract the sdist archive and return the path to the source.
        """
        if sdist.lower().endswith(".zip"):
            open_sdist = zipfile.ZipFile
            error_cls = zipfile.BadZipfile
        else:
            assert ".tar" in sdist.lower()
            open_sdist = tarfile.TarFile.open
            error_cls = tarfile.ReadError
        try:
            with contextlib.closing(open_sdist(sdist)) as archive:
                archive.extractall(path=dest)

            def collapse_trivial(path):
                entries = os.listdir(path)
                if len(entries) == 1:
                    entry = os.path.join(path, entries[0])
                    if os.path.isdir(entry):
                        return collapse_trivial(entry)
                return path

            return collapse_trivial(dest)
        except error_cls:
            raise BuildException("Failed to extract %s" % os.path.basename(sdist))

    def build_wheel_from_sdist(self, sdist):
        """
        Given a sdist archive extract it, build in a temporary directory, and
        put the wheel into the downloads directory.
        """
        temp = tempfile.mkdtemp()
        try:
            source = self.extract_sdist(sdist, temp)
            # Make sure to import setuptools and wheel in the setup.py.
            # This is happening in a temporary directory, so we will just
            # overwrite the setup.py to add our own imports.
            setup_py = os.path.join(source, "setup.py")
            with open(setup_py, "r") as f:
                original = f.read()
            with open(setup_py, "w") as f:
                f.write("import setuptools\n")
                f.write("import wheel\n")
                f.write(original)
            # Build the wheel
            command = [
                sys.executable,
                setup_py,
                "bdist_wheel",
                "-d",
                os.path.abspath(self._dest),
            ]
            subprocess.check_call(command, cwd=source)
        except subprocess.CalledProcessError:
            raise BuildException("Failed to build %s" % str(os.path.basename(sdist)))
        finally:
            xar_util.safe_rmtree(temp)

    def find(self, requirement):
        """
        Ensure all built wheels are added to the working set.
        Return the distribution.
        """
        finders.register_finders()
        for dist in pkg_resources.find_distributions(self._dest):
            if dist not in self._working_set:
                self._working_set.add(dist, entry=self._dest)
        return self._working_set.find(requirement)

    def __call__(self, requirement):
        """
        Attempts to download the requirement (and its dependencies) and add the
        wheel(s) to the downloads directory and the working set. Returns the
        distribution on success and None on failure.
        """
        # Remove non-wheels from the download directory
        self.clean()
        # Attempt to download the wheel/sdist
        try:
            self.download(requirement)
        except PipException as e:
            if self._log:
                self._log.exception(e)
            return None
        # Build wheels for the sdists (and remove the sdist)
        for entry in os.listdir(self._dest):
            if py_util.Wheel.is_wheel_archive(entry):
                continue
            try:
                sdist = os.path.join(self._dest, entry)
                self.build_wheel_from_sdist(sdist)
                xar_util.safe_remove(sdist)
            except BuildException as e:
                if self._log:
                    self._log.exception(e)
                return None
        # Return the wheel distribution
        return self.find(requirement)
