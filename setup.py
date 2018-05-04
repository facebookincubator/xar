from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from setuptools import setup

from xar.commands.bdist_xar import bdist_xar

setup(
    name='xar',
    version='0.1',
    description="The XAR packaging toolchain.",
    url='https://github.com/facebook/xar',
    packages=[
        'xar',
        'xar.commands',
    ],
    install_requires=[
        # Version 34.1 fixes a bug in the dependency resolution. If this is
        # causing an problem for you, please open an issue, and we can evaluate
        # a workaround. (grep setuptools>=34.1 to see issue)
        # https://github.com/pypa/setuptools/commit/8c1f489f09434f42080397367b6491e75f64d838  # noqa: B950
        "setuptools>=34.1",
        "wheel",
    ],
    test_requires=[
        "pytest",
    ],
    entry_points={
        'distutils.commands': [
            'bdist_xar = xar.commands.bdist_xar:bdist_xar',
        ],
        'console_scripts': [
            'make_xar = xar.make_xar:main',
        ],
    },
    # Add the bdist_xar command in so
    cmdclass={'bdist_xar': bdist_xar},
)
