# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import tempfile
import unittest

from xar import py_util, xar_util


try:
    from unittest import mock
except ImportError:
    import mock


THISDIR = os.path.dirname(__file__)
TESTWHEEL = os.path.join(THISDIR, "test-1.0-py2.py3-none-win32.whl")


class PyUtilTest(unittest.TestCase):
    def test_environment_python_interpreter(self):
        interpreter = py_util.environment_python_interpreter()
        self.assertTrue(interpreter.startswith("/usr/bin/env"))

    def test_wheel_determine_kind_normal(self):
        distribution = mock.MagicMock(egg_info="xar-18.6.11-py3-none-any.whl")
        wheel = py_util.Wheel(distribution=distribution)
        lib = "/usr/lib/python/site-packages"
        paths = {
            "purelib": lib,
            "platlib": lib,
            "headers": "/usr/include/xar",
            "scripts": "/usr/bin",
            "data": "/usr",
        }
        k, p = wheel._determine_kind(lib, paths, paths, lib + "/tmp")
        self.assertTrue(k == "purelib" or k == "platlib")
        self.assertEqual(p, lib)
        k, p = wheel._determine_kind(lib, paths, paths, "/usr/none")
        self.assertEqual(k, "data")
        self.assertEqual(p, "/usr")
        k, p = wheel._determine_kind(lib, paths, paths, "/usr/bin/make_xar")
        self.assertEqual(k, "scripts")
        self.assertEqual(p, "/usr/bin")
        k, p = wheel._determine_kind(lib, paths, paths, "/usr/include/xar/x")
        self.assertEqual(k, "headers")
        self.assertEqual(p, "/usr/include/xar")

    def test_wheel_determine_kind_mac(self):
        distribution = mock.MagicMock(egg_info="xar-18.6.11-py3-none-any.whl")
        wheel = py_util.Wheel(distribution=distribution)
        lib = "/usr/lib/python/site-packages"
        paths = {
            "purelib": lib,
            "platlib": lib,
            "headers": "/bad/prefix/include/xar",
            "scripts": "/bad/prefix/bin",
            "data": "/bad/prefix",
        }
        k, p = wheel._determine_kind(lib, paths, paths, lib + "/tmp")
        self.assertTrue(k == "purelib" or k == "platlib")
        self.assertEqual(p, lib)
        k, p = wheel._determine_kind(lib, paths, paths, "/usr/none")
        self.assertEqual(k, "data")
        self.assertEqual(p, "/usr")
        k, p = wheel._determine_kind(lib, paths, paths, "/usr/bin/make_xar")
        self.assertEqual(k, "scripts")
        self.assertEqual(p, "/usr/bin")
        k, p = wheel._determine_kind(lib, paths, paths, "/usr/include/xar/x")
        self.assertEqual(k, "headers")
        self.assertEqual(p, "/usr/include/xar")

    def test_does_sha256_match(self):
        expected = "sha256=uU0nuZNNPgilLlLX2n2r-sSE7-N6U4DukIj3rOLvzek"
        unexpected = "sha256=XARXARXARXARXARXARXARXARXARXARXARXARXARXARX"
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"hello world")
            file = f.name
        self.assertTrue(py_util.does_sha256_match(file, expected))
        self.assertFalse(py_util.does_sha256_match(file, unexpected))
        self.assertFalse(py_util.does_sha256_match(file, ""))

    def _temppaths(self, root):
        return {
            "purelib": root,
            "platlib": root,
            "headers": os.path.join(root, "include/xar"),
            "scripts": os.path.join(root, "bin"),
            "data": root,
        }

    def test_wheel_copy_installation(self):
        dist = mock.MagicMock()
        dist.location = "/path/to/lib/xar"
        dist.egg_info = "/path/to/lib/xar-18.7.12.dist-info"
        wheel = py_util.Wheel(distribution=dist)

        wheel.is_purelib = mock.MagicMock(return_value=True)
        wheel.records = mock.MagicMock(
            return_value=[
                ["xar/0", "sha256=uU0nuZNNPgilLlLX2n2r-sSE7-N6U4DukIj3rOLvzek", 11],
                ["xar/1", "", 11],
                ["xar/2", "sha256=uU0nuZNNPgilLlLX2n2r-sSE7-N6U4DukIj3rOLvzek", 11],
                ["xar/2", "sha256=uU0nuZNNPgilLlLX2n2r-sSE7-N6U4DukIj3rOLvzek", 11],
            ]
        )

        src = tempfile.mkdtemp()
        os.mkdir(os.path.join(src, "xar"))
        dst = tempfile.mkdtemp()

        for file, _, _ in wheel.records():
            with open(os.path.join(src, file), "wb") as f:
                f.write(b"hello world")

        wheel.copy_installation(self._temppaths(src), self._temppaths(dst))

        for file, hash, _ in wheel.records():
            dst_file = os.path.join(dst, file)
            self.assertTrue(os.path.exists(dst_file))
            matches = py_util.does_sha256_match(dst_file, hash)
            if hash:
                self.assertTrue(matches)
            else:
                self.assertFalse(matches)

        xar_util.safe_rmtree(src)
        xar_util.safe_rmtree(dst)

    def test_wheel_sys_install_paths(self):
        print(TESTWHEEL)
        wheel = py_util.Wheel(location=TESTWHEEL)
        sys_paths = wheel.sys_install_paths()
        for path in self._temppaths(""):
            self.assertTrue(path in sys_paths)

    def test_wheel_is_purelib(self):
        print(TESTWHEEL)
        wheel = py_util.Wheel(location=TESTWHEEL)
        self.assertFalse(wheel.is_purelib())

    def _check_install(self, paths):
        def assertExists(*path):
            self.assertTrue(os.path.exists(os.path.join(*path)))

        assertExists(paths["platlib"], "hello.pyd")
        assertExists(paths["platlib"], "hello", "hello.py")
        assertExists(paths["platlib"], "hello", "__init__.py")
        assertExists(paths["data"], "hello.dat")
        assertExists(paths["headers"], "hello.dat")
        assertExists(paths["scripts"], "hello.sh")
        assertExists(paths["platlib"], "test-1.0.dist-info", "RECORD")

    def test_wheel_install_archive(self):
        print(TESTWHEEL)
        self.assertTrue(py_util.Wheel.is_wheel_archive(TESTWHEEL))
        wheel = py_util.Wheel(location=TESTWHEEL)
        dst = tempfile.mkdtemp()
        paths = self._temppaths(dst)

        # Install without force
        wheel.install_archive(paths, force=False)
        self._check_install(paths)

        # Reinstall with force
        wheel.install_archive(paths, force=True)
        self._check_install(paths)

        xar_util.safe_rmtree(dst)

    def test_wheel_install(self):
        archived_wheel = py_util.Wheel(location=TESTWHEEL)
        src = tempfile.mkdtemp()
        dst = tempfile.mkdtemp()
        src_paths = self._temppaths(src)
        dst_paths = self._temppaths(dst)

        # Install the archive to src
        archived_wheel.install(None, src_paths)
        self._check_install(src_paths)

        # Copy the installation to dst
        src_location = os.path.join(src, "test-1.0.dist-info")
        self.assertFalse(py_util.Wheel.is_wheel_archive(src_location))
        installed_wheel = py_util.Wheel(location=src_location)
        installed_wheel.install(src_paths, dst_paths, force=False)
        self._check_install(dst_paths)

        # Reinstall copy to dst with force
        installed_wheel.install(src_paths, dst_paths, force=True)
        self._check_install(dst_paths)

        xar_util.safe_rmtree(src)
        xar_util.safe_rmtree(dst)
