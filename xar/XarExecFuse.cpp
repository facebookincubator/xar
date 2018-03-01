// Copyright 2004-present Facebook.  All rights reserved.
//
// This binary is a helper binary used as part of a shebang file in
// front of a squashfs file to mount the squash via FUSE and then run
// a command from inside it.
//
// As this is executed like...
// #!/sbin/xarexec_fuse
//
// The program receives its arguments in an unusual way; argv[0] is
// the executable, argv[1] is the *entire* tail after the executable
// in the shebang line, argv[2] is the path to the xar file, and
// argv[3:] are parameters the user specified.
//
// The actual squash file in the xar file begins at the 4096 byte
// offset.
//
// A UUID is in the XAR header to allow every XAR to be mounted in a
// unique location. The squash file is mounted relative to
// /mnt/xarfuse (in the structure /mnt/xarfuse/uid-N-ns-Y/UUID so each user
// has their own mountpoint) or to an alternative mountpoint specified
// (ie: /dev/shm).

#include <algorithm>
#include <cctype>
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>

// struct statfs is in sys/mount.h on macOS.
#ifdef __APPLE__
#include <sys/mount.h>
#else
#include <sys/statfs.h>
#endif

#include <sys/wait.h>
#include <unistd.h>
#include <cstdlib>

#include "XarHelpers.h"

namespace {

// Headers we specifically look for.
const char* kOffsetName = "OFFSET";
const char* kXarexecTarget = "XAREXEC_TARGET";
const char* kUuidName = "UUID";
const char* kMountRoot = "MOUNT_ROOT";

// Default timeout to pass to squashfuse_ll.  14.5 minutes;
// clean_xar_mounts uses 15 minutes
const size_t kSquashFuseDefaultTimeout = 870;
const char* kSquashFuseExecutable = "/usr/bin/squashfuse_ll";
const char* kSquashFuseTimeoutKillswitch =
  "/var/lib/xarexec_timeout_killswitch";

using std::cout;
using std::cerr;
using std::endl;

// Set to true for verbose output when testing.
bool debugging = false;

// For check_file_sanity -- do we expect a file, or a directory?
enum class Expectation { Directory = 1, File = 2 };

// Quick, simple checks for file sanity; make sure we match the
// permissions we want as well as the type of file and owner.
void check_file_sanity(
    const std::string& path,
    enum Expectation expected,
    mode_t perms) {
  struct stat st;
  PCHECK_SIMPLE(stat(path.c_str(), &st) == 0);
  if (st.st_uid != geteuid()) {
    cerr << "Invalid owner of " << path << endl;
    abort();
  }

  // Verify the directory is owned by one of the groups the user is in.
  if (st.st_gid != getegid() && !tools::xar::is_user_in_group(st.st_gid)) {
    cerr << "Invalid group of " << path << endl;
    abort();
  }

  if (expected == Expectation::Directory && !S_ISDIR(st.st_mode)) {
    cerr << "Should be a directory: " << path << endl;
    abort();
  }
  if (expected == Expectation::File && !S_ISREG(st.st_mode)) {
    cerr << "Should be a normal file: " << path << endl;
    abort();
  }
  if ((st.st_mode & 07777) != perms) {
    cerr << "Invalid permissions on " << path << ", expected " << std::oct
         << perms << ", got " << (st.st_mode & 07777) << endl;
    abort();
  }
}

const std::vector<std::string> kDefaultMountRoots{"/mnt/xarfuse", "/dev/shm"};

std::string get_user_basedir(const std::string& basedir) {
  auto ret = basedir + "/uid-" + std::to_string(geteuid());

  mkdir(ret.c_str(), 0755); // ignore failure
  check_file_sanity(ret, Expectation::Directory, 0755);
  return ret;
}

// Acquire a lock to prevent races to set up the mount.
int grab_lock(const std::string& lockfile) {
  int fd = open(lockfile.c_str(), O_RDWR | O_CREAT | O_CLOEXEC, 0600);
  if (fd < 0) {
    cerr << "can't open lockfile: " << strerror(errno) << endl;
    abort();
  }

  check_file_sanity(lockfile, Expectation::File, 0600);
  if (flock(fd, LOCK_EX) != 0) {
    cerr << "can't flock lockfile: " << strerror(errno) << endl;
    abort();
  }

  return fd;
}

// Extract the UUID, OFFSET, XAREXEC_TARGET, and other parameters from
// the XAR header.
const size_t kDefaultHeaderSize = 4096;
std::unordered_map<std::string, std::string> read_xar_header(
    const char* filename) {
  int fd = open(filename, O_RDONLY | O_CLOEXEC);
  if (fd < 0) {
    cerr << "open " << filename << ": " << strerror(errno) << endl;
    abort();
  }

  std::string buf;
  buf.resize(kDefaultHeaderSize);
  ssize_t res = read(fd, &buf[0], buf.size());
  if (res < 0) {
    cerr << "read header from: " << filename << ": " << strerror(errno) << endl;
    abort();
  }
  if (res != buf.size()) {
    cerr << "Short read of header of " << filename << endl;
    abort();
  }
  res = close(fd);
  if (res < 0) {
    cerr << "close " << filename << ": " << strerror(errno) << endl;
    abort();
  }

  std::unordered_map<std::string, std::string> ret;
  auto lines = tools::xar::split('\n', buf);
  for (const auto& line : lines) {
    if (line == "#xar_stop") {
      break;
    }
    if (line.empty() || line[0] == '#') {
      continue;
    }

    auto name_value = tools::xar::split('=', line);
    if (name_value.size() != 2) {
      cerr << "malformed header line: " << line << endl;
      abort();
    }
    std::string name = name_value[0];
    std::string value = name_value[1];

    if (name.empty() || value.size() < 2 || value.front() != '"' ||
        value.back() != '"') {
      cerr << "invalid line in xar header: " << line << endl;
      abort();
    }
    // skip quotes around value
    ret[name] = value.substr(1, value.size() - 2);
  }

  if (ret.find(kOffsetName) == ret.end() ||
      ret[kOffsetName] != std::to_string(kDefaultHeaderSize)) {
    cerr << "TODO(chip): support headers other than the default" << endl;
    abort();
  }

  if (ret.find(kUuidName) == ret.end()) {
    cerr << "No UUID in XAR header" << endl;
    abort();
  }

  if (debugging) {
    for (const auto& p : ret) {
      cerr << "header " << p.first << "=" << p.second << endl;
    }
  }

  return ret;
}

bool is_squashfuse_mounted(const std::string& path, bool try_fix) {
  struct statfs statfs_buf;
  if (statfs(path.c_str(), &statfs_buf) != 0) {
    if (!try_fix) {
      return false;
    }
    if (errno == ENOTCONN) {
      std::string cmd = tools::xar::UNMOUNT_CMD + path;
      if (system(cmd.c_str()) != 0) {
        cerr << "unable to umount broken mount; try 'fusermount -u " << path
             << "' by hand" << endl;
        abort();
      }
      return false;
    }
    cerr << "stafs failed for " << path << ": " << strerror(errno) << endl;
    abort();
  }

  return tools::xar::is_squashfs_mounted(statfs_buf);
}

// Close all file descriptors; we can't rely on the caller doing this,
// as there are cases where passing an fd to a child process is
// reasonable.  We want to ensure the squashfuse_ll subprocess,
// however, is not hanging on to anything unexpected.
//
// Also replace fd 0, 1, and 2 with /dev/null if they are not already
// open.
void sanitize_file_descriptors() {
  // Close all fds that aren't 0, 1, 2.
  tools::xar::close_non_std_fds();

  // Replace fd 0, 1, and 2 with reasonable /dev/null descriptors if
  // they aren't already open.  Since open always returns the lowest
  // unopened fd, we can just open and refuse to close if the fd is
  // what we want.
  int in_fd = open("/dev/null", O_RDONLY);
  PCHECK_SIMPLE(in_fd >= 0);
  if (in_fd > 0) {
    close(in_fd);
  }

  // Fill fd 1 and 2 with /dev/null if they're not already open.
  while (true) {
    int out_fd = open("/dev/null", O_WRONLY);
    PCHECK_SIMPLE(out_fd >= 0);
    if (out_fd > 2) {
      close(out_fd);
      break;
    }
  }
}

// Set timeout based on the XAR_MOUNT_TIMEOUT environment variable.
// If it is empty, or the killswitch file exists, use no timeout; if
// it is unset, use the default.  Otherwise, it is the timeout (in
// seconds) to pass to squashfuse_ll.
size_t get_squashfuse_timeout() {
  if (access(kSquashFuseTimeoutKillswitch, F_OK) == 0) {
    return 0UL;
  }
  const auto env_timeout = getenv("XAR_MOUNT_TIMEOUT");
  if (env_timeout) {
    return std::strtoul(env_timeout, nullptr, 10);
  } else {
    return kSquashFuseDefaultTimeout;
  }
}

void usage() {
  cerr << "Usage: xarexec [-m|-n] /path/to/file.xar" << endl
       << "Options: " << endl
       << "     -m: mount and print mountpoint, do not execute payload" << endl
       << "     -n: print the mountpoint but don't mount" << endl;
}

} // namespace

int main(int argc, char** argv) {
  CHECK_SIMPLE(getuid() == geteuid());
  // Set our umask to a good default for the files we create.  Save
  // the old value to restore before executing the XAR bootstrap
  // script.
  auto old_umask = umask(0022);

  if (argc < 2) {
    usage();
    return 1;
  }

  // Skip past our executable name, the optional -m flag, and, after
  // stashing a copy of it, the path to the xar file.  This leaves
  // argv[0:argc-1] as the parameters to pass to the process we exec.
  argv++;
  argc--;
  bool mount_only = false;
  bool print_only = false;
  while (argv[0] && argv[0][0] == '-') {
    if (strcmp(argv[0], "-m") == 0) {
      mount_only = true;
    } else if (strcmp(argv[0], "-n") == 0) {
      print_only = true;
    } else if (strcmp(argv[0], "-h") == 0) {
      usage();
      return 0;
    } else {
      usage();
      return 1;
    }
    argv++;
    argc--;
  }
  if (!argv[0]) {
    usage();
    return 1;
  }
  char* xar_path = argv[0];
  argv++;
  argc--;

  // Extract our required fields from the XAR header.  XAREXEC_TARGET
  // is required unless the -m flag was used.
  auto header = read_xar_header(xar_path);
  size_t offset;
  try {
    size_t end;
    offset = std::stoull(header[kOffsetName], &end);
    if (end != header[kOffsetName].size()) {
      throw std::invalid_argument("Offset not entirely an integer");
    }
  } catch (const std::exception& ex) {
    cerr << "Header offset is non-integral: " << header[kOffsetName] << endl;
    cerr << "Exact error: " << ex.what() << endl;
    abort();
  }
  std::string uuid = header[kUuidName];
  std::string execpath;
  auto it = header.find(kXarexecTarget);
  if (it != header.end()) {
    execpath = it->second;
  }
  if (!mount_only && execpath.empty()) {
    cerr << "No XAREXEC_TARGET in XAR header of " << xar_path << endl;
    abort();
  }
  if (!std::all_of(uuid.begin(), uuid.end(), isxdigit)) {
    cerr << "uuid must only contain hex digits" << endl;
    abort();
  }
  if (uuid.empty()) {
    cerr << "uuid must be non-empty" << endl;
    abort();
  }

  // If provided, use a non-default mount root from the header.
  std::string mountroot;
  it = header.find(kMountRoot);
  if (it != header.end()) {
    mountroot = it->second;
  } else {
    // Otherwise find the first proper mount root from our list of
    // defaults.
    for (const auto& candidate : kDefaultMountRoots) {
      struct stat st;
      if (stat(candidate.c_str(), &st) == 0 &&
          (st.st_mode & 07777) == 01777) {
        mountroot = candidate;
        break;
      }
    }
    if (mountroot.empty()) {
      cerr << "Unable to find suitable 01777 mount root" << endl;
      abort();
    }
  }

  struct stat st;
  PCHECK_SIMPLE(stat(mountroot.c_str(), &st) == 0);
  if ((st.st_mode & 07777) != 01777) {
    cerr << "Should be 01777: " << mountroot << endl;
    abort();
  }

  // Path is /mnt/xarfuse/uid-N-ns-Y/UUID; we make directories under
  // /mnt/xarfuse as needed. Replace /mnt/xarfuse with custom
  // values as specified.
  std::string user_basedir = get_user_basedir(mountroot);
  std::string mount_path = user_basedir + "/" + uuid;

  // mtab sucks.  In some environments, particularly centos6, when
  // mtab is shared between different mount namespaces, we want to
  // disambiguate by more than just the XAR's uuid and user's uid.  We
  // use the mount namespace id, but optionally also take a
  // user-specified "seed" from the environment.  We cannot rely
  // purely on mount namespace as the kernel will aggressively re-use
  // namespace IDs, so while namespace helps with concurrent jobs, it
  // can fail with jobs run after other jobs.
  auto env_seed = getenv("XAR_MOUNT_SEED");
  if (env_seed && *env_seed && strchr(env_seed, '/') == nullptr) {
    mount_path += "-seed-";
    mount_path += env_seed;
  }

  const size_t squashfuse_idle_timeout = get_squashfuse_timeout();

  // Try to determine our mount namespace id (via the inode on
  // /proc/self/ns/mnt); if we can, make that part of our mountpoint's
  // name.  This ensures that /etc/mtab on centos6 has unique entries
  // for processes in different namespaces, even if /etc itself is
  // shared among them.  See t12007704 for details.
  // Note: will fail on macOS.
  if (stat("/proc/self/ns/mnt", &st) == 0) {
    mount_path += "-ns-" + std::to_string(st.st_ino);
  }

  if (print_only) {
    cout << mount_path << endl;
    return 0;
  }

  int lock_fd = grab_lock(user_basedir + "/lockfile." + uuid);
  if (mkdir(mount_path.c_str(), 0755) != 0) {
    if (errno != EEXIST) {
      cerr << "mkdir failed"
           << ": " << strerror(errno) << endl;
      abort();
    }
  }

  // TODO(chip): also mount DEPENDENCIES
  if (!is_squashfuse_mounted(mount_path, true)) {
    // Check mount_path sanity before mounting; once mounted, though,
    // the permissions may change, so we have to do the check after we
    // grab the lock but know we need to perform a mount.
    check_file_sanity(mount_path, Expectation::Directory, 0755);

    pid_t pid = fork();
    PCHECK_SIMPLE(pid >= 0);
    if (pid == 0) {
      sanitize_file_descriptors();
      std::string opts = "-ooffset=" + std::to_string(offset);
      if (squashfuse_idle_timeout > 0) {
        opts += ",timeout=" + std::to_string(squashfuse_idle_timeout);
      }
      if (tools::xar::fuse_allows_visible_mounts("/etc/fuse.conf")) {
        opts += ",allow_root";
      }
      PCHECK_SIMPLE(
          execl(
              kSquashFuseExecutable,
              kSquashFuseExecutable,
              opts.c_str(),
              xar_path,
              mount_path.c_str(),
              nullptr) == 0);
    } else {
      int status = 0;
      PCHECK_SIMPLE(waitpid(pid, &status, 0) == pid);
      // We only make it out of this block if we have an exit status of 0.
      if (WIFEXITED(status)) {
        if (WEXITSTATUS(status) != 0) {
          cerr << "squashfuse_ll failed with exit status "
               << WEXITSTATUS(status) << endl;
          abort();
        }
      } else if (WIFSIGNALED(status)) {
          cerr << "squashfuse_ll failed with signal "
               << WTERMSIG(status) << endl;
          abort();
      } else {
          cerr << "squashfuse_ll failed with unknown exit status "
               << status << endl;
          abort();
      }
    }
  }

  // Wait for up to 9 seconds for mount to be available
  auto start = std::chrono::steady_clock::now();
  auto timeout = std::chrono::seconds(9);
  while (!is_squashfuse_mounted(mount_path, false)) {
    if (std::chrono::steady_clock::now() - start > timeout) {
      cerr << "timed out waiting for squashfs mount" << endl;
      abort();
    }
    /* sleep override */
    std::this_thread::sleep_for(std::chrono::microseconds(100));
  }

  // Touch the lockfile; our unmount script will use it as a proxy for
  // unmounting "stale" mounts.
  PCHECK_SIMPLE(futimes(lock_fd, nullptr) == 0);

  if (mount_only) {
    cout << mount_path << endl;
    return 0;
  }

  // Construct our exec path; if it already exists, we're done and can
  // simply execute it.
  const std::string exec_path = mount_path + "/" + execpath;
  if (debugging) {
    cerr << "exec: " << exec_path << " as " << getuid() << " " << getgid()
         << endl;
  }

  // Hold a file descriptor open to one of the files in the XAR; this
  // will prevent unmounting as we exec the bootstrap and it execs
  // anything.  Intentionally not O_CLOEXEC.  This is necessary
  // because the exec call typically targets a shell script inside the
  // XAR and so the script won't remain open while the exec happens --
  // the kernel will examine it, run a bash process, and that will
  // open the shell script.  Between the parsing and bash opening it,
  // the mount point could disappear.  Also, that script itself often
  // exec's the python interpreter living on local disk, which will
  // open a py file in the XAR... again a brief moment where the
  // unmount can occur.
  int bootstrap_fd = open(exec_path.c_str(), O_RDONLY);
  if (bootstrap_fd == -1) {
    cerr << "Unable to open " << exec_path << ": " << strerror(errno) << endl;
    abort();
  }

  // cmd line is:
  // newArgs[0] = mounted path inside squash file to run
  // newArgs[1] = path to the squash file itself
  // newArgs[2], newArgs[3], ... = args passed on our command line

  // Why argc + 3?  The 2 new params and the trailing nullptr entry.
  char* newArgs[argc + 3];
  newArgs[0] = strdup(exec_path.c_str());
  if (newArgs[0] == nullptr) {
    cerr << "strdup failed, call the cops"
         << ": " << strerror(errno) << endl;
    abort();
  }
  newArgs[1] = xar_path;
  for (int i = 0; i < argc; ++i) {
    newArgs[i + 2] = argv[i];
  }
  newArgs[argc + 2] = nullptr;
  for (int i = 0; newArgs[i]; ++i) {
    if (debugging) {
      cerr << "  exec arg: " << newArgs[i] << endl;
    }
  }
  umask(old_umask);
  if (execv(newArgs[0], newArgs) != 0) {
    cerr << "execv: " << strerror(errno) << "cmd: " << newArgs[0] << endl;
    abort();
  }

  return 0;
}
