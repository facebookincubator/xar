# Copyright (c) 2018-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function, unicode_literals

import unittest

from xar import py_util


try:
    from unittest import mock
except ImportError:
    import mock


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
