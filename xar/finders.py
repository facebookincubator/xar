# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function

import os
import pkgutil
import zipimport

import pkg_resources
from xar import py_util


try:
    import importlib.machinery as importlib_machinery

    # access attribute to force import under delayed import mechanisms.
    importlib_machinery.__name__
except ImportError:
    importlib_machinery = None


def find_wheels_in_zip(importer, path_item, only=False):
    try:
        yield py_util.Wheel(location=path_item, importer=importer).distribution
    except Exception:
        pass


def find_wheels_on_path(importer, path_item, only=False):
    if only or not os.path.isdir(path_item) or not os.access(path_item, os.R_OK):
        return
    for entry in os.listdir(path_item):
        if py_util.Wheel.is_wheel_archive(entry):
            location = os.path.join(path_item, entry)
            for dist in pkg_resources.find_distributions(location):
                yield dist


def find_on_path(importer, path_item, only=False):
    for finder in (pkg_resources.find_on_path, find_wheels_on_path):
        for dist in finder(importer, path_item, only):
            yield dist


__REGISTERED = False


def register_finders():
    """
    Register pkg_resources finders that work with wheels (but not eggs). These
    replace the default pkg_resources finders. This function should be called
    before calling pkg_resources.find_distributions().
    """
    global __REGISTERED
    if __REGISTERED:
        return

    pkg_resources.register_finder(zipimport.zipimporter, find_wheels_in_zip)
    pkg_resources.register_finder(pkgutil.ImpImporter, find_on_path)
    if hasattr(importlib_machinery, "FileFinder"):
        pkg_resources.register_finder(importlib_machinery.FileFinder, find_on_path)

    __REGISTERED = True
