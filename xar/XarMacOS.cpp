#include <algorithm>
#include <array>
#include <iostream>
#include <string>
#include <vector>

#include <libproc.h>
#include <sys/mount.h>
#include <sys/proc_info.h>
#include <sys/types.h>
#include <unistd.h>
#include <cstdio>

#include "tools/xar/XarHelpers.h"

// Unmount on macOS.
const char* tools::xar::UNMOUNT_CMD = "umount ";

// Gets the output of a system command (similar to python's
// subprocess.call_output).
std::string call_output(const std::string& cmd) {
  FILE* out_file = popen(cmd.c_str(), "r");
  if (!out_file) {
    return "";
  }

  // Get output from command.
  constexpr size_t size = 256;
  std::array<char, size> buffer;
  std::string output;
  while (!std::feof(out_file)) {
    if (std::fgets(buffer.data(), buffer.size(), out_file) != nullptr) {
      output.append(buffer.data());
    }
  }

  pclose(out_file);
  return output;
}

bool tools::xar::is_user_in_group(gid_t dir_gid) {
  auto user_groups = call_output("id -G " + std::to_string(geteuid()));
  if (user_groups.empty()) {
    return false;
  }

  auto str_gids = split(' ', user_groups);
  return std::find_if(
             std::begin(str_gids),
             std::end(str_gids),
             [dir_gid](const std::string& gid_str) {
               return static_cast<gid_t>(std::stoi(gid_str)) == dir_gid;
             }) != std::end(str_gids);
}

// macOS doesn't have /proc, so use proc_pidinfo() instead (see
// http://fburl.com/712863205549035).
void tools::xar::close_non_std_fds() {
  // Get list of pids (and their types).
  int buffer_size = proc_pidinfo(getpid(), PROC_PIDLISTFDS, 0, nullptr, 0);
  if (buffer_size < 0) {
    std::cerr << "Can't get open fd's on macOS, bailing" << std::endl;
    abort();
  }
  auto num_pids = static_cast<size_t>(buffer_size) / sizeof(proc_fdinfo);
  std::vector<proc_fdinfo> proc_fds(num_pids, proc_fdinfo{});
  proc_pidinfo(getpid(), PROC_PIDLISTFDS, 0, proc_fds.data(), buffer_size);

  // Close each fd, but only if it's PROX_FDTYPE_VNODE and not any of [0, 1, 2].
  for (auto fd : proc_fds) {
    if (fd.proc_fdtype == PROX_FDTYPE_VNODE && fd.proc_fd > 2) {
      close(fd.proc_fd);
    }
  }
}

// On macOS it's easier to check the fs typename. The filesystem type seems to
// change a lot.
bool tools::xar::is_squashfs_mounted(const struct statfs& buf) {
  auto fsname = std::string{buf.f_fstypename};
  return fsname == "osxfuse" || fsname == "osxfusefs";
}

bool tools::xar::fuse_allows_visible_mounts(std::string fuse_conf_path) {
  return false;
}
