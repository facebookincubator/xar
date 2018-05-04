import os
from setuptools import setup

from xar.commands.bdist_xar import bdist_xar


CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))


def get_long_description():
    with open(os.path.join(CURRENT_DIR, "README.md"), "r") as ld_file:
        return ld_file.read()


setup(
    name="xar",
    version="0.69",
    description="The XAR packaging toolchain.",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    author="Chip Turner",
    author_email="chip@fb.com",
    url="https://github.com/facebook/xar",
    license="BSD",
    packages=["xar", "xar.commands"],
    install_requires=[
        # Version 34.1 fixes a bug in the dependency resolution. If this is
        # causing an problem for you, please open an issue, and we can evaluate
        # a workaround. (grep setuptools>=34.1 to see issue)
        # https://github.com/pypa/setuptools/commit/8c1f489f09434f42080397367b6491e75f64d838  # noqa: E501
        "setuptools>=34.1",
        "wheel",
    ],
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
    # Add the bdist_xar command in so
    cmdclass={"bdist_xar": bdist_xar},
)
