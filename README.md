# XAR
XARs are the replacement for PARs, JSARs, LARs, and other executable archive systems. It is used to package up Python modules into a single
executable file.

A XAR file is a [squashfs](https://en.wikipedia.org/wiki/SquashFS) image.  
The first four kilobytes, though, are shell script, whose shebang references
`xarexec_fuse`, who is responsible for mounting the squashfs file into a known
location and then executing something inside the XAR file
(the "something" typically is a bootstrap script).

More details are in `OVERVIEW.md`

## Requirements
XAR requires:
* Mac OS X or Linux
* Python >= **2.7.11** & >= **3.5**

## Building XAR
XAR has multiple components.

### C++ Fuse Modules
This code requires `squashfuse` installed.

```
mkdir build && cmake .. && make && [sudo] make install
```

### bdist_xar
The setuptools plugin is available on PyPI. This module will require `squashfs-tools`

```
pip install xar
```

*or*

```
python setup.py install
```



## Installing XAR


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
XAR is BSD-licensed. We also provide an additional patent grant.
