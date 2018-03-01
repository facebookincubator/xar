# XAR Files

XAR (pronounced like "czar" aka like "zar") files are an extension of
the PAR/LAR system currently in use at Facebook.  XAR files are
effectively SquashFS files with a special pre-amble that contains
metadata and, optionally, a shebang which allows for executing the XAR
file.

The 'X' is just a placeholder for all other letters, much like the 'X'
in 'XDB.'

# SquashFS 101

SquashFS files are a form of loopback mounting available in the Linux
kernel.  They are read-only and support high levels of compression,
which can significantly reduce space (3-5x in many cases) while also
allowing the distribution of a single file rather than thousands.
They are often used for holding root filesystems for, say, LiveCD
distributions; in other words, the codepaths are very well tested.  In
addition, Facebook already makes heavy use of SquashFS files for
distributing the www release to webis.

# Use Cases

There are two primary use cases for XAR files.  The first is simply
collecting a number of files for automatic, atomic mounting somewhere
on the filesystem.  The main example here would be the fbcode
runtimes; using a XAR file vastly shrinks the on-disk size of the
runtimes (3.9GB -> 715MB, or ~18% of its original size, when maximal
compression is desired), saving multiple gigabytes per machine and
reducing random disk IO.  This is important on flash machines.

The second use case is an extension of the first -- by making the XAR
file executable and using the xarexec helper, a XAR becomes a packaged
collection of executables and data (such as Python files and shared
libraries). This can replace PAR and LAR files with a system that is
faster, has less overhead, is more compatible, and achieves better
compression.  The downside is that it requires a setuid helper to
perform the mounting.

# XAR file details

A XAR file is a header (typically 4k) followed by a SquashFS file.
The header contains metadata such as unique IDs, build timestamps,
etc, which aid in mounting each XAR file deterministically.  The
header is actually valid shell scripts, so the XAR file can be
executable and easily parsed by tools.  If the shebang points to
xarexec then, when executed, the XAR file will be mounted and an inner
executable will be invoked.

# Dependencies

A XAR file can list one or more other XAR files as dependencies; these
will be mounted when the XAR file is mounted.  Soft and hard
dependencies are supported for debuginfo files (optional and not
necessary to function) and required files (required for the XAR to
execute properly).  The use case for hard dependencies is from
"sparse" PAR files, where common files among many PAR files can be
stored once in a ependent SPAR file.

## How Dependencies Work

The idea is to move some files from the main XAR into dependent XARs.
The files in the original XAR are replaced with relative symlinks that
point to where the other XARs would be mounted.  In some cases (such
as debuginfo XARs), the symlinks may dangle.  In the future, when sparse
XARs are implemented, the symlinks should not dangle.

# Full example: fbcode runtime

This example splits an fbcode runtime into two XAR files, one for most
files, and the other for debuginfo.  It then mounts them with
`mount_xar.py`, which creates symlinks in `/usr/local/fbcode-runtime`
to the actual mountpoints (`/mnt/xar/...`).  From that point, all
files (regardless of which XAR they were in) can be accessed via
`/usr/local/fbcode-runtime` in an atomic way (i.e., if we replace the
XAR files and re-run `mount_xar.py`, the old mountpoint remains but
the symlink points to the mountpoints of the new XAR file).

`
$ make_xar --directory /usr/local/fbcode/gcc-4.8.1-glibc-2.17-fb \
           --output /tmp/gcc-4.8.1-glibc-2.17-fb.xar \
           --partition_extensions .debuginfo \
           --optimize=size
$ du -hsc /tmp/gcc-4.8.1-glibc-2.17-fb*.xar
309M	/tmp/gcc-4.8.1-glibc-2.17-fb.debuginfo.xar
120M	/tmp/gcc-4.8.1-glibc-2.17-fb.xar
total	428M
$ du -sh /usr/local/fbcode/gcc-4.8.1-glibc-2.17-fb
1.1G	/usr/local/fbcode/gcc-4.8.1-glibc-2.17-fb
$ sudo tools/xar/mount_xar.py  --symlink /tmp/fbcode-symlinks /tmp
... output ...
$ ls -l /tmp/fbcode-symlinks/
lrwxrwxrwx. 1 root root 45 May 12 07:17 gcc-4.8.1-glibc-2.17-fb -> /mnt/xar/gcc-4.8.1-glibc-2.17-fb.xar-dc5cf18f
lrwxrwxrwx. 1 root root 55 May 12 07:17
gcc-4.8.1-glibc-2.17-fb.debuginfo ->
/mnt/xar/gcc-4.8.1-glibc-2.17-fb.debuginfo.xar-d26275dc
$ ls -l /tmp/fbcode-symlinks/gcc-4.8.1-glibc-2.17-fb/bin/gdb.debuginfo
lrwxrwxrwx. 1 nobody nobody 67 May 12 07:11 /tmp/fbcode-symlinks/gcc-4.8.1-glibc-2.17-fb/bin/gdb.debuginfo -> ../../gcc-4.8.1-glibc-2.17-fb.debuginfo.xar-d26275dc/bin/gdb.debuginfo

`

# Full example: twutil.par

Let's xarify `twcli_wrapper.par` (which is used for the tupperware
command line tools).  It already is small, as the debug symbols have
been stripped:

`
$ ls -l /usr/facebook/tupperware/cli/bin/twcli_wrapper.par
-rwxr-xr-x. 1 root root 66612196 Apr 27 12:43 /usr/facebook/tupperware/cli/bin/twcli_wrapper.par
$ make_xar.lpar --xar_exec /bin/xarexec_fuse \
                --inner_executable=xar_bootstrap.sh \
                --parfile=/usr/facebook/tupperware/cli/bin/twcli_wrapper.par \
                --output=/tmp/twcli_wrapper.xar \
                --optimize=speed
$ ls -l /tmp/twcli_wrapper.xar
-rwxr-xr-x. 1 chip users 49737728 May 12 07:41 /tmp/twcli_wrapper.xar
$ /tmp/twcli_wrapper.xar --help
Please supply one of `twdeploy`, `twutil`, or `twcanary` as an argument
$ du -sh /tmp/par_unpack.twcli_wrapper.3435.4e50f4471fbb4988e1708d31eabb1f65/
164M	/tmp/par_unpack.twcli_wrapper.3435.4e50f4471fbb4988e1708d31eabb1f65/
$ find /tmp/par_unpack.twcli_wrapper.3435.4e50f4471fbb4988e1708d31eabb1f65/ | wc
    849     849   82089
`

Here we see a PAR file's dirty secret -- 164MB of space for the
decompressed parts of the PAR file (mainly .so libraries).  This means
twcli_wrapper.par uses ~250mb of space after execution, while the XAR
version uses ~48M (and doesn't increase when executed, since it is
simply mounted and not expanded on-disk).

The `--optimize` parameter here optimizes for speed of execution, but
it can also optimize for size (resulting in a smaller XAR file, but
first execution is slower).  The Linux block cache caches
*uncompressed* blocks, though, so only first use requires
decompression.

# Misc Notes / TODOs

## Using XARs for fbcode runtimes

To do this, we need to decide where to drop xar files and then run the
mount script at boot time.  Alternatively, we could perhaps have fstab
automatically generate entries for xar files we care about.  This is
made more complicated because we need to have the XARs mounted before
anything tries to use the fbcode runtime.

## Transition plan

All of the XAR tools exist outside of the fbcode build system itself;
this is intentional for two reasons: 1) fbconfig/fbmake are being
replaced, so work to integrate there would need to be duplicated; and
2), not everything we might want to XAR comes from an fbcode build.

In the future, integration with Buck as a first-class `par_style`
(and, eventually, the default for `python_binary` and `lua_binary`) is
the goal.

## Executable XARs

Executable XARs work by having a shebang that invokes xarexec, which
needs to be setuid root (or else only root can run XAR files).

TODO: Implement a fallback that expands a xar file on disk

### Performance

Using `twcli_wrapper.par` as an example again, let's see performance
of first-invocation and second-invocation at different compression
levels and against native par files:

Type: size, first-run, second-run
PAR (zipfile/decompressed): 64M/164M, 2.668s, 1.261s
XAR (lzo, 64k block): 70M, 1.255s, 0.991s
XAR (gzip, 64k block): 63M, 1.603s, 0.943s
XAR (xz, 64k, block): 54M, 3.259s, 0.990s
XAR (xz, 1024k, block): 48M, 6.546s, 0.974s

As shown above, XARs allow for a spectrum of choices for trading off
speed vs size, but once run, all compression levels result in the same
speed of execution.  This tradeoff can be made on a per-XAR basis (and
even having different dependencies, such as debuginfo XARs, compressed
more than the main executable).

Even LZO compression is a significant win, but gzip is probably
reasonable as a default.
