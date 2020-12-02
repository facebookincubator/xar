# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from setuptools import setup


CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))


def get_long_description():
    with open(os.path.join(CURRENT_DIR, "README.md"), "r") as ld_file:
        return ld_file.read()


setup(
    name="xar",
    version="20.12.2",
    description="The XAR packaging toolchain.",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    author="Chip Turner",
    author_email="chip@fb.com",
    url="https://github.com/facebookincubator/xar",
    license="BSD",
    packages=[
        "xar",
        "xar.commands",
        "xar.tests",
        "xar.vendor",
        "xar.vendor.wheel",
        "xar.vendor.wheel.signatures",
    ],
    install_requires=[
        "pip>=10.0.1",
        # Version 34.1 fixes a bug in the dependency resolution. If this is
        # causing an problem for you, please open an issue, and we can evaluate
        # a workaround. (grep setuptools>=34.1 to see issue)
        # https://github.com/pypa/setuptools/commit/8c1f489f09434f42080397367b6491e75f64d838  # noqa: E501
        "setuptools>=34.1",
    ],
    tests_require=["mock", "pytest"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Framework :: Setuptools Plugin",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3.6",
    ],
    entry_points={
        "distutils.commands": ["bdist_xar = xar.commands.bdist_xar:bdist_xar"],
        "console_scripts": ["make_xar = xar.make_xar:main"],
    },
)
