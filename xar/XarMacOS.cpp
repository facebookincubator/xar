// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#include <algorithm>
#include <string>
#include <vector>

#include <libproc.h>
#include <pwd.h>
#include <sys/proc_info.h>
#include <unistd.h>

#include "XarHelpers.h"

// This is clowny, but it works. This is an undocumented function built into
// libc/libSystem on macOS. It actually returns all groups a user is a member
// of (unlike getgroups, which only returns up to some maximum).
// Needs C-linkage since it's in libc/libSystem.
extern "C" {
int32_t getgrouplist_2(const char* username, gid_t base_gid, gid_t** gids);
}

// Unmount on macOS.
const char* tools::xar::UNMOUNT_CMD = "umount ";

bool tools::xar::is_user_in_group(gid_t dir_gid) {
  auto user = getpwuid(geteuid());
  gid_t* gids = nullptr;
  auto ngroups = getgrouplist_2(user->pw_name, user->pw_gid, &gids);
  PCHECK_SIMPLE(ngroups > -1);
  return std::find(gids, gids + ngroups, dir_gid) != gids + ngroups;
}

// macOS doesn't have /proc, so use proc_pidinfo() instead (see
// http://fburl.com/712863205549035).
void tools::xar::close_non_std_fds() {
  // Get list of pids (and their types).
  int buffer_size = proc_pidinfo(getpid(), PROC_PIDLISTFDS, 0, nullptr, 0);
  PCHECK_SIMPLE(buffer_size > -1);
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
  return fsname == "osxfuse" || fsname == "osxfusefs" || fsname == "macfuse";
}

bool tools::xar::fuse_allows_visible_mounts(std::string fuse_conf_path) {
  return false;
}

static const char kDataMountPoint[] = "/System/Volumes/Data/mnt/xarfuse";
static const char kRootMountPoint[] = "/mnt/xarfuse";

std::vector<std::string> tools::xar::default_mount_roots() {
  return {kDataMountPoint, kRootMountPoint, "/dev/shm"};
}

void tools::xar::no_mount_roots_help_message(std::ostream& out) {
  out << "Unable to find suitabe 01777 mount root. "
      << "Try: mkdir $DIR && chmod 01777 $DIR. For DIR=" << kDataMountPoint
      << " on MacOS 10.15 Catalina or later and DIR=" << kRootMountPoint
      << " on earlier MacOS versions.";
}
