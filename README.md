# XAR

<p align="center">
<a href="https://circleci.com/gh/facebookincubator/xar"><img alt="CircleCI Status" src="https://circleci.com/gh/facebookincubator/xar.svg?style=shield&circle-token=79452315bcb15c6fa74a3af99829bb8b31ee366d"></a>
<a href="https://github.com/ambv/black"><img alt="Code style: black" src="https://img.shields.io/badge/code%20style-black-000000.svg"></a>
<a href="https://pepy.tech/project/xar"><img alt="Downloads" src="https://pepy.tech/badge/xar"></a>
</p>

XAR lets you package many files into a single self-contained executable file.
This makes it easy to distribute and install.

A `.xar` file is a read-only file system image which, when mounted, looks like
a regular directory to user-space programs.  This requires a one-time
installation of a driver for this file system
([SquashFS](https://en.wikipedia.org/wiki/SquashFS)).

XAR is pronounced like "czar" (/t͡ʂar/).  The 'X' in XAR is meant to be
a placeholder for all other letters as at Facebook this format was originally
designed to replace ZIP-based PAR (Python archives), JSAR (JavaScript archives),
LAR (Lua archives), and so on.


## Use Cases

There are two primary use cases for XAR files.  The first is simply collecting
a number of files for automatic, atomic mounting somewhere on the filesystem.
Using a XAR file vastly shrinks the on-disk size of the data it holds.
Compressing to below 20% of the original size is not unheard of.  This can save
multiple gigabytes per machine and reduce random disk IO.  This is especially
important on machines with flash storage.

The second use case is an extension of the first -- by making the XAR file
executable and using the `xarexec` helper, a XAR becomes a self-contained
package of executable code and its data.  A popular example is Python
application archives that include all Python source code files, as well as
native shared libraries, configuration files, other data.

This can replace virtualenvs and PEX files with a system that is faster, has
less overhead, is more compatible, and achieves better compression.
The downside is that it requires a setuid helper to perform the mounting.


## Advantages of XAR for Python usage

* SquashFS looks like regular files on disk to Python. This lets it use regular
  imports which are better supported by CPython.

* SquashFS looks like regular files to your application, too. You don't need to
  use `pkg_resources` or other tricks to access data files in your package.

* SquashFS with Zstandard compression saves disk space, also compared to a ZIP
  file.

* SquashFS doesn't require unpacking of `.so` files to a temporary location like
  ZIP files do.

* SquashFS is faster to start up than unpacking a ZIP file. You only need to
  mount the file system once. Subsequent calls to your application will reuse
  the existing mount.

* SquashFS only decompresses the pages that are used by the application, and
  decompressed pages are cached in the page cache.

* SquashFS is read-only so the integrity of your application is guaranteed
  compared to using virtualenvs or unpacking to a temporary directory.

## Benchmarks

Optimizing performance (both space and execution time) was a key design goal for
XARs. We ran benchmark tests with open source tools to compare PEX, XAR, and
native installs on the following metrics:

* **Size:** file size, in bytes, of the executable
* **Cold start time:** time taken when we have nothing mounted or extracted
* **Hot start time:** time taken when we have extracted cache or mounted XAR squashfs

The PEXs are built with `python3 setup.py bdist_pex --bdist-all`, and the XARs
are built with `python3 setup.py bdist_xar --xar-compression-algorithm=zstd`.

| Console script        | Size               | Cold start time | Hot start time |
|-----------------------|--------------------|-----------------|----------------|
| django-admin (native) |  22851072 B        | -               | 0.220 s        |
| django-admin.pex      |   8529089 B        | 1.705 s         | 0.772 s        |
| django-admin.xar      |   5464064 B (-36%) | 0.141 s (-92%)  | 0.122 s (-84%) |
| black (native)        |   1020928 B        | -               | 0.245 s        |
| black.pex             |    677550 B        | 0.737 s         | 0.619 s        |
| black.xar             |    307200 B (-55%) | 0.245 s (-67%)  | 0.219 s (-65%) |
| jupyter (native)      |  64197120 B        | -               | 0.399 s        |
| jupyter.pex           |  17315669 B        | 2.152 s         | 1.046 s        |
| jupyter.xar           |  17530880 B (+1%)  | 0.213 s (-90%)  | 0.181 s (-83%) |

The results show that both file size (with [zstd compression]) and start times
improve with XARs. This is an improvement when shipping to large number of
servers, especially with short-running executables, such as small data
collection scripts on web servers or interactive command line tools.

[zstd compression]: https://code.fb.com/core-data/smaller-and-faster-data-compression-with-zstandard/

## Requirements
XAR requires:
* Linux or macOS
* Python >= **2.7.11** & >= **3.5**
* [squashfs-tools](https://github.com/plougher/squashfs-tools) to build XARs
* [squashfuse](https://github.com/vasi/squashfuse) >= 0.1.102 **with**
  `squashfuse_ll` to run XARs


## Components of XAR

### bdist_xar

This is a setuptools plugin that lets you package your Python application
as a .xar file.  It requires `squashfs-tools`.  Install it from PyPI to get
the stable version:

```
pip install xar
```

*or* you can install it from this repository:

```
python setup.py install
```

After installation go to your favorite Python project with a console script and
run:

```
python setup.py bdist_xar
```

The setuptools extension `bdist_xar` has options to configure the XAR, most
importantly `--interpreter` sets the Python interpreter used. Run
`python setup.py bdist_xar --help` for a full list of options.

### xarexec_fuse

This is a binary written in C++ used to mount a SquashFS image.
It requires `squashfuse` installed. Note that the current `squashfuse` package
on Ubuntu doesn't include `squashfuse_ll`, so you will have to install from
[source](https://github.com/vasi/squashfuse/releases).

You can build this part of the code with:

```
mkdir build && cd build && cmake .. && make && [sudo] make install
```

## Examples

### bdist_xar

Simply run:

```
python /path/to/black/setup.py bdist_xar [--xar-compression-algorithm=zstd]
/path/to/black/dist/black.xar --help
```

### make_xar

XAR provides a simple CLI to create XARs from Python executables or directories.
We can create a XAR from an existing Python executable zip file, like a PEX.

```
make_xar --python black.pex --output black.xar
```

You can also create a XAR from a directory, and tell XAR which executable to
run once it starts.

```
> mkdir myxar
> echo -n "#\!/bin/sh\nshift\necho \$@" > myxar/echo
> chmod +x myxar/echo
> make_xar --raw myxar --raw-executable echo --output echo
> ./echo hello world
hello world
```

`xarexec_fuse` will execute the executable it is given using the XAR path as the
first argument, and will forward the XARs arguments after.

## Running the Circle CI tests locally

First you need to install docker (and possible docker-machine), as it is how it
runs the the code. Then you need to
[install](https://circleci.com/docs/2.0/local-cli/) the `circleci` cli, and run

    circleci build

If you change `.circleci/config.yml` you should validate it before committing

    circleci config validate


## Contributing
See the CONTRIBUTING file for how to help out.


## License
XAR is BSD-licensed.
