# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import pkg_resources
from xar import pip_installer, xar_util


try:
    from unittest import mock
except ImportError:
    import mock


HELLO_SETUP_PY = """
from setuptools import setup
import wheel

setup(
    name="hello",
    version="0.0.0",
    packages=["hello"],
    entry_points={
        "console_scripts": ["hello = hello"],
    },
)
"""


class PyUtilTest(unittest.TestCase):
    def setUp(self):
        self.src = tempfile.mkdtemp()
        setup_py = os.path.join(self.src, "setup.py")
        xar_util.safe_mkdir(os.path.join(self.src, "hello"))
        with open(os.path.join(self.src, "README"), "w") as f:
            f.write("hello\n")
        with open(os.path.join(self.src, "hello/__init__.py"), "w") as f:
            f.write("print('hello')\n")
        with open(setup_py, "w") as f:
            f.write(HELLO_SETUP_PY)

        subprocess.check_call([sys.executable, setup_py, "bdist_wheel"], cwd=self.src)
        subprocess.check_call([sys.executable, setup_py, "sdist"], cwd=self.src)

        dist_dir = os.path.join(self.src, "dist")
        dists = os.listdir(dist_dir)
        self.assertEqual(len(dists), 2)
        if dists[0].lower().endswith(".whl"):
            self.wheel = os.path.join(dist_dir, dists[0])
            self.sdist = os.path.join(dist_dir, dists[1])
        else:
            self.wheel = os.path.join(dist_dir, dists[1])
            self.sdist = os.path.join(dist_dir, dists[0])
        self.req = pkg_resources.Requirement("hello")
        self.dst = tempfile.mkdtemp()

    def tearDown(self):
        xar_util.safe_rmtree(self.src)
        xar_util.safe_rmtree(self.dst)

    def mock_download_sdist(self, _req):
        shutil.copy(self.sdist, self._dest)

    def mock_download_wheel(self, _req):
        shutil.copy(self.wheel, self._dest)

    @mock.patch.object(pip_installer.PipInstaller, "download", mock_download_wheel)
    def test_pip_install_wheel(self):
        working_set = pkg_resources.WorkingSet(sys.path)
        installer = pip_installer.PipInstaller(self.dst, working_set)
        installer.sdist = self.sdist
        installer.wheel = self.wheel
        dist = installer(self.req)
        self.assertTrue(dist in self.req)

    @mock.patch.object(pip_installer.PipInstaller, "download", mock_download_sdist)
    def test_pip_install_sdist(self):
        working_set = pkg_resources.WorkingSet(sys.path)
        installer = pip_installer.PipInstaller(self.dst, working_set)
        installer.sdist = self.sdist
        installer.wheel = self.wheel
        dist = installer(self.req)
        self.assertTrue(dist in self.req)
