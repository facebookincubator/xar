// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#[macro_use]
extern crate clap;
extern crate failure;
#[macro_use]
extern crate lazy_static;
extern crate nix;
extern crate regex;
#[macro_use]
extern crate slog;
extern crate slog_term;

use clap::{App, Arg};
use regex::Regex;
use slog::Drain;
use std::collections::HashMap;
use std::fs;
use std::fs::File;
use std::io::{BufRead, BufReader};

use std::os::linux::fs::MetadataExt;
use std::os::unix::io::RawFd;
use std::path::PathBuf;
use std::process::Command;
use std::str::FromStr;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

type Result<T> = ::std::result::Result<T, failure::Error>;

// jemalloc can be configured with a static string.  We have to
// null-terminate it, but this works fine from Rust.
//
// We disable the background thread because the setns syscall fails
// with EINVAL if a process has more than one thread.  See "man setns"
// for details.
#[allow(non_upper_case_globals)]
#[no_mangle]
pub static malloc_conf: &str = "background_thread:false\0";

/// flock a file descriptor of the given type within timeout_sec.
/// Return True if successful.
fn flock_with_timeout(fd: RawFd, timeout_sec: u64) -> bool {
    let start = Instant::now();
    while start.elapsed().as_secs() < timeout_sec {
        let lock = nix::fcntl::flock(fd, nix::fcntl::FlockArg::LockExclusiveNonblock);
        if !lock.is_err() {
            return true;
        }
        thread::sleep(Duration::from_millis(10));
    }
    false
}

#[cfg(test)]
extern crate tempfile;
#[cfg(test)]
use std::os::unix::io::AsRawFd;

#[test]
fn test_flock_with_timeout() {
    // Basic test; create a tempfile, lock it, then ensure we can't
    // re-lock it until closing the original file.
    let tf1 = tempfile::NamedTempFile::new().unwrap();
    let fd1 = tf1.as_raw_fd();
    assert!(flock_with_timeout(fd1, 10));

    // We have to re-open rather than dup because dup copies the lock,
    // too.
    let tf2 = File::open(tf1.path()).unwrap();
    let fd2 = tf2.as_raw_fd();
    assert!(!flock_with_timeout(fd2, 1));

    // Drop the tempfile, which closes the fd; ensure we can now
    // perform a lock.
    let tf3 = File::open(tf1.path()).unwrap();
    let fd3 = tf3.as_raw_fd();
    drop(tf1);

    assert!(flock_with_timeout(fd3, 1));
}

#[derive(Clone)]
struct MountNamespaceInfo {
    namespace_path: PathBuf,
    chroot_path: PathBuf,
    pid: u64,
}

/// Return a list of MountNamespaceInfo that span all unique namespaces.
fn get_mount_namespaces() -> Result<Vec<MountNamespaceInfo>> {
    // The inode of the /proc/PID/ns/mnt file (not the symlink itself,
    // but the dereferenced symlink) is the namespace id.  Build a
    // HashMap mapping the namespace id to an arbitrary symlink that
    // pointed to it.
    let mut namespace_dedup = HashMap::new();
    for entry in fs::read_dir("/proc")? {
        let entry = entry.unwrap();
        let entry_name = entry.file_name().into_string().unwrap();
        let pid = match u64::from_str(&entry_name) {
            Ok(pid) => pid,
            Err(_) => continue,
        };
        if !entry.file_type()?.is_dir() {
            continue;
        }
        let namespace_path = PathBuf::from(format!("/proc/{}/ns/mnt", entry_name));
        let inode = match fs::metadata(&namespace_path) {
            Ok(st) => st.st_ino(),
            Err(_) => continue,
        };
        let chroot_path = match fs::read_link(PathBuf::from(format!("/proc/{}/root", entry_name))) {
            Ok(path) => path,
            Err(_) => continue,
        };
        namespace_dedup.insert(
            inode,
            MountNamespaceInfo {
                namespace_path,
                chroot_path,
                pid,
            },
        );
    }
    Ok(namespace_dedup.into_iter().map(|p| p.1).collect())
}

/// Simple structure representing the system's current mounts.
#[derive(Debug)]
struct MountedFilesystem {
    mountpoint: String,
    chroot: PathBuf,
    fstype: String,
}

/// Return a vector of MountedFilesystems relative to a given mount
/// namespace.
fn get_mounts(
    nsinfo: &MountNamespaceInfo,
    logger: &slog::Logger,
) -> Result<Vec<MountedFilesystem>> {
    // Read the process' mounts from our own process and mount
    // namespace.
    let proc_mounts_path = PathBuf::from(format!("/proc/{}/mounts", nsinfo.pid));

    let file = BufReader::new(File::open(proc_mounts_path)?);
    let mut mounts = Vec::new();
    for line in file.lines() {
        if let Ok(line) = line {
            let mut fields = line.split(' ').skip(1).take(2).map(str::to_string);
            // mtab can be escaped; fix it up before calling umount.
            // Details:
            // https://gnu.org/software/libc/manual/html_node/mtab.html
            // Note backslashes are just '\134' and not '\0134' - special
            // case.
            let mut mountpoint = fields
                .next()
                .expect("missing mountpoint field")
                .replace("\\134", "\\");
            for ch in "\t\r\n ".chars() {
                let replacement = ch.to_string();
                let needle = format!("\\{:o}", ch as u8);
                mountpoint = mountpoint.replace(&needle, &replacement);
            }
            let fstype = fields.next().unwrap();
            mounts.push(MountedFilesystem {
                mountpoint,
                chroot: nsinfo.chroot_path.clone(),
                fstype,
            })
        } else if let Err(ref e) = line {
            info!(logger, "Skipping invalid line: {:?} ({})", line, e);
        }
    }
    return Ok(mounts);
}

// Simple test to exercise walking the host's mounts and mount
// namespaces.
#[test]
fn parse_mounts_test() {
    let logger = setup_logger(slog::Level::Debug);
    let mount_namespaces = get_mount_namespaces().unwrap();
    assert!(mount_namespaces.len() > 0);
    for nsinfo in mount_namespaces {
        let mounts = get_mounts(&nsinfo, &logger).unwrap();
        assert!(mounts.len() > 0);
        for mount in mounts {
            let _result = should_unmount(&logger, &mount, 1).unwrap();
        }
    }
}

/// Basic structure representing whether we should or shouldn't
/// unmount a given mountpoint.  In some cases, we need to hold a
/// flock'd fd open until the rmdir is performed, so we track the
/// optional fd in this struct.
struct ShouldUnmountResult {
    should_unmount: bool,
    lock_fd: Option<i32>,
}

impl ShouldUnmountResult {
    fn new(should_unmount: bool, lock_fd: Option<i32>) -> ShouldUnmountResult {
        ShouldUnmountResult {
            should_unmount,
            lock_fd,
        }
    }
}

impl Drop for ShouldUnmountResult {
    fn drop(&mut self) {
        if let Some(fd) = self.lock_fd {
            nix::unistd::close(fd).expect("close should not fail");
        }
    }
}

/// A simple structure that, when created, changes to a specified
/// mount namespace and, when drop'd, returns to the original mount
/// namespace.
struct NamespaceSaver {
    orig_ns_fd: i32,
}

impl NamespaceSaver {
    fn new(orig_ns_fd: i32, nspath: &PathBuf) -> Result<NamespaceSaver> {
        let temp_ns_fd = nix::fcntl::open(
            nspath,
            nix::fcntl::OFlag::O_RDONLY,
            nix::sys::stat::Mode::from_bits(0700).unwrap(),
        )?;
        nix::sched::setns(temp_ns_fd, nix::sched::CloneFlags::CLONE_NEWNS)?;
        nix::unistd::close(temp_ns_fd).expect("close should not fail");

        Ok(NamespaceSaver { orig_ns_fd })
    }
}

impl Drop for NamespaceSaver {
    fn drop(&mut self) {
        nix::sched::setns(self.orig_ns_fd, nix::sched::CloneFlags::CLONE_NEWNS)
            .expect("could not restore default mount namespace");
    }
}

#[test]
fn get_lockfile_test() {
    // Helper to make a MountedFilesystem object.
    fn make_mf(mountpoint: &str) -> MountedFilesystem {
        MountedFilesystem {
            mountpoint: String::from(mountpoint),
            chroot: PathBuf::from("/"),
            fstype: String::from("fuse.squashfuse_ll"),
        }
    }

    let logger = setup_logger(slog::Level::Debug);

    // Confirm parsing a non-seed'd directory works
    let mf = make_mf("/mnt/xarfuse/uid-0/8f583eae-ns-4026531840");
    assert_eq!(
        get_lockfile_path(&logger, &mf),
        vec![
            PathBuf::from("/mnt/xarfuse/uid-0/lockfile.8f583eae-ns-4026531840"),
            PathBuf::from("/mnt/xarfuse/uid-0/lockfile.8f583eae"),
        ]
    );

    // Confirm parsing a non-seed'd /dev/shm directory works
    let mf = make_mf("/dev/shm/uid-0/8f583eae-ns-4026531840");
    assert_eq!(
        get_lockfile_path(&logger, &mf),
        vec![
            PathBuf::from("/dev/shm/uid-0/lockfile.8f583eae-ns-4026531840"),
            PathBuf::from("/dev/shm/uid-0/lockfile.8f583eae"),
        ],
    );

    // Confirm parsing a seed'd directory works
    let mf = make_mf("/mnt/xarfuse/uid-0/8f583eae-seed-test-ns-4026531840");
    assert_eq!(
        get_lockfile_path(&logger, &mf),
        vec![
            PathBuf::from("/mnt/xarfuse/uid-0/lockfile.8f583eae-seed-test-ns-4026531840"),
            PathBuf::from("/mnt/xarfuse/uid-0/lockfile.8f583eae"),
        ],
    );

    // Confirm parsing a seed'd directory with dashes works
    let mf = make_mf("/mnt/xarfuse/uid-0/8f583eae-seed-test-foo-bar-ns-4026531840");
    assert_eq!(
        get_lockfile_path(&logger, &mf),
        vec![
            PathBuf::from("/mnt/xarfuse/uid-0/lockfile.8f583eae-seed-test-foo-bar-ns-4026531840"),
            PathBuf::from("/mnt/xarfuse/uid-0/lockfile.8f583eae"),
        ],
    );

    // Confirm a random path doesn't parse
    let mf = make_mf("/dev/null");
    assert!(get_lockfile_path(&logger, &mf).len() == 0);
}

fn get_lockfile_path(logger: &slog::Logger, mount: &MountedFilesystem) -> Vec<PathBuf> {
    // Strip off the dir the mountpoint is inside (only from a list of
    // valid prefixes).  If the mount isn't prefixed by our list, do
    // not unmount.
    let mount_suffix_opt = ["/mnt/xarfuse/", "/dev/shm/"]
        .iter()
        .filter_map(|candidate| {
            if mount.mountpoint.starts_with(candidate) {
                Some(&mount.mountpoint[candidate.len()..])
            } else {
                None
            }
        })
        .next();

    let mount_suffix = match mount_suffix_opt {
        Some(mnt) => mnt,
        None => {
            info!(
                logger,
                "Skipping unmount of {}, incorrect prefix", mount.mountpoint
            );
            return vec![];
        }
    };
    debug!(logger, "Mount suffix: {}", mount_suffix);

    // Mounts are of the form /prefix/uid-N/UUID-ns-NSID/... or
    // /prefix/uid-N/UUID-seed-SEED-ns-NSID/... -- we need to extract
    // the UUID portion.
    lazy_static! {
        static ref UUID_REGEX: Regex =
            Regex::new(r"^uid-\d+/([^/-]+)(?:-seed-(?:[^/]+))?-ns-([^-/]+)$").unwrap();
    }

    // Validate our filename looks like a mountpoint we care about,
    // and extract the UUID for the legacy lockfile.
    let captures = match UUID_REGEX.captures(&mount_suffix) {
        Some(captures) => captures,
        None => return vec![],
    };
    let uuid = captures.get(1).unwrap();

    // Look for the lockfile for the mountpoint; there are two cases,
    // one of just a lockfile.UUID (old style) and one of
    // lockfile.MOUNT_DIR (new style, which includes the UUID, seed,
    // and namespace).
    let mut lockfile_base = mount.chroot.clone();
    lockfile_base.push(&mount.mountpoint[1..]); // strip leading slash
    lockfile_base.set_file_name("lockfile");

    let mut old_lockfile = lockfile_base.clone();
    old_lockfile.set_extension(uuid.as_str());

    let mut new_lockfile = lockfile_base.clone();
    new_lockfile.set_extension(PathBuf::from(mount_suffix).file_name().unwrap());

    vec![new_lockfile, old_lockfile]
}

/// Check whether a mount point should be unmounted.  We only consider
/// squashfuse mounts in the correct locations.  Returns a
/// ShouldUnmountResult.
fn should_unmount(
    logger: &slog::Logger,
    mount: &MountedFilesystem,
    timeout: u32,
) -> Result<ShouldUnmountResult> {
    // Only consider certain mount types.
    match mount.fstype.as_str() {
        "fuse.squashfuse" | "fuse.squashfuse_ll" | "osxfusefs" | "osxfuse" => {}
        _ => return Ok(ShouldUnmountResult::new(false, None)),
    }
    info!(
        logger,
        "Considering {} ({})", mount.mountpoint, mount.fstype
    );

    let lockfiles = get_lockfile_path(&logger, &mount);

    // Sometimes mtab gets out of sync with reality; all XARs should
    // contain files, so let's confirm they actually do, and if not,
    // still consider them for unmounting.
    let mut chrooted_mountpoint = mount.chroot.clone();
    chrooted_mountpoint.push(&mount.mountpoint[1..]);
    if let Ok(it) = fs::read_dir(&chrooted_mountpoint) {
        if it.take_while(|r| r.is_ok()).next().is_none() {
            debug!(
                logger,
                "Unmounting empty directory: {:?}", chrooted_mountpoint
            );
            return Ok(ShouldUnmountResult::new(true, None));
        }
    } else {
        info!(
            logger,
            "Unable to read dir {:?}, skipping emptiness check", chrooted_mountpoint
        );
    }

    debug!(logger, "lockfile candidates: {:?}", lockfiles);

    // Find the lockfile; use its mtime to determine if the mount
    // point is old enough to try to reap.
    let lock_opt = lockfiles
        .iter()
        .map(|ref filename| {
            nix::fcntl::open(
                filename.as_path().as_os_str(),
                nix::fcntl::OFlag::O_RDWR | nix::fcntl::OFlag::O_CLOEXEC,
                nix::sys::stat::Mode::from_bits(0700).unwrap(),
            )
        })
        .filter_map(|open_result| open_result.ok())
        .next();
    let lock_fd = match lock_opt {
        Some(fd) => fd,
        None => {
            debug!(
                logger,
                "Unable to find lock file for {}, skipping...", mount.mountpoint
            );
            return Ok(ShouldUnmountResult::new(true, None));
        }
    };

    // lock the file before checking timestamp to protect against a
    // race with XarexecFuse.
    if !flock_with_timeout(lock_fd, 60) {
        info!(
            logger,
            "Unable to flock {:?}, skipping...", chrooted_mountpoint
        );
        return Ok(ShouldUnmountResult::new(false, lock_opt));
    }
    let stat = nix::sys::stat::fstat(lock_fd)?;
    let epoch_now = SystemTime::now().duration_since(UNIX_EPOCH)?;
    let age = epoch_now - Duration::new(stat.st_mtime as u64, stat.st_mtime_nsec as u32);
    let timeout = Duration::from_secs(timeout as u64 * 60);
    if age <= timeout {
        info!(
            logger,
            "Skipping unmount of {}, too recent ({:.2}s)",
            mount.mountpoint,
            age.as_secs() as f64 + age.subsec_nanos() as f64 / 1000000000.0
        );
        return Ok(ShouldUnmountResult::new(false, lock_opt));
    }

    Ok(ShouldUnmountResult::new(true, lock_opt))
}

fn setup_logger(level: slog::Level) -> slog::Logger {
    let drain = slog_term::PlainSyncDecorator::new(std::io::stdout());
    let drain = slog_term::FullFormat::new(drain).build();
    let drain = slog::LevelFilter::new(drain, level).fuse();
    slog::Logger::root(drain, o![])
}

// This is our main function.
fn run() -> Result<()> {
    let matches = App::new("Clean XAR Mounts")
        .arg(
            Arg::with_name("timeout")
                .long("timeout")
                .default_value("15")
                .help("time, in minutes, after a xar was mounted to attempt to unmount it"),
        )
        .arg(
            Arg::with_name("verbose")
                .long("verbose")
                .short("v")
                .help("display detailed output"),
        )
        .arg(
            Arg::with_name("dryrun")
                .long("dry-run")
                .help("display detailed output"),
        )
        .get_matches();
    let timeout = value_t!(matches, "timeout", u32)?;
    let dryrun = matches.is_present("dryrun");
    let level = if matches.is_present("verbose") {
        slog::Level::Debug
    } else {
        slog::Level::Info
    };

    let root_log = setup_logger(level);

    let orig_ns_fd = nix::fcntl::open(
        "/proc/self/ns/mnt",
        nix::fcntl::OFlag::O_RDONLY,
        nix::sys::stat::Mode::from_bits(0700).unwrap(),
    )?;
    let mount_namespaces = get_mount_namespaces()?;
    info!(
        root_log,
        "Considering {} namespaces",
        mount_namespaces.len()
    );
    for nsinfo in mount_namespaces {
        info!(
            root_log,
            "Entering namespace {:?}...", nsinfo.namespace_path
        );
        // Enter the new namespace and then check /proc/mounts for the
        // now-visible mounts.
        let mounts = get_mounts(&nsinfo, &root_log);
        if mounts.is_err() {
            info!(
                root_log,
                "Unable to read mounts in {:?}", nsinfo.namespace_path
            );
            continue;
        }
        let _ns_saver = NamespaceSaver::new(orig_ns_fd, &nsinfo.namespace_path);
        if _ns_saver.is_err() && nix::unistd::geteuid().is_root() {
            info!(
                root_log,
                "Unable to enter namespace {:?}, skipping", nsinfo.namespace_path
            );
            continue;
        }
        for mount in mounts.unwrap() {
            let result = should_unmount(&root_log, &mount, timeout)?;
            if result.should_unmount {
                // TODO: consider forking and chrooting into the
                // process' chroot rather than constructing a path
                // from outside.  It may not always be true that we
                // can append paths to find the actual mount point to
                // unmount.
                let mut target = mount.chroot.clone();
                target.push(&mount.mountpoint[1..]); // strip leading slash
                info!(
                    root_log,
                    "unmounting {:?}:{:?}", nsinfo.namespace_path, target
                );
                if !dryrun {
                    if nix::unistd::geteuid().is_root() {
                        if let Err(e) = nix::mount::umount(&target) {
                            info!(root_log, "Failed to unmount {:?}: {}", target, e);
                        }
                    } else {
                        let output = Command::new("fusermount").arg("-u").arg(&target).output()?;
                        if !output.status.success() {
                            info!(
                                root_log,
                                "fusermount -u failed to unmount {:?}: {}",
                                target,
                                String::from_utf8_lossy(&output.stderr).trim()
                            );
                        }
                    }
                }
            }
        }
    }
    Ok(())
}

// Boilerplate main to print errors nicely.
fn main() {
    std::env::set_var("RUST_BACKTRACE", "1");
    if let Err(ref e) = run() {
        use std::io::Write; // trait which holds `display`
        let stderr = &mut ::std::io::stderr();
        let errmsg = "Error writing to stderr";

        writeln!(stderr, "{}, {}", e.as_fail(), e.backtrace()).expect(errmsg);
        ::std::process::exit(1);
    }
}
