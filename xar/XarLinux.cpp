// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#include <iostream>

#include <dirent.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/vfs.h>
#include <unistd.h>
#include <cstdlib>

#include "Logging.h"
#include "XarHelpers.h"

#define FUSE_SUPER_MAGIC 0x65735546

const char* tools::xar::UNMOUNT_CMD = "/bin/fusermount -z -q -u ";

bool tools::xar::is_user_in_group(gid_t dir_gid) {
  size_t num_groups = getgroups(0, nullptr);
  gid_t user_group_list[num_groups];
  int group_count = getgroups(sizeof(user_group_list), user_group_list);
  XAR_PCHECK_SIMPLE(group_count > -1);

  for (int i = 0; i < group_count; ++i) {
    if (user_group_list[i] == dir_gid) {
      return true;
    }
  }

  return false;
}

void tools::xar::close_non_std_fds() {
  auto dir_fd = open("/proc/self/fd", O_RDONLY | O_DIRECTORY);
  DIR* dir_handle = nullptr;
  if (dir_fd >= 0 && (dir_handle = fdopendir(dir_fd))) {
    for (auto dent = readdir(dir_handle); dent; dent = readdir(dir_handle)) {
      if (strcmp(dent->d_name, ".") == 0 || strcmp(dent->d_name, "..") == 0) {
        continue;
      }

      int fd = std::atoi(dent->d_name);
      if (fd != dir_fd && fd > 2) {
        close(fd);
      }
    }
    closedir(dir_handle);
  }
}

// On linux, squashfs has filesystem type FUSE_SUPER_MAGIC.
bool tools::xar::is_squashfs_mounted(const struct statfs& buf) {
  return buf.f_type == FUSE_SUPER_MAGIC;
}

bool tools::xar::fuse_allows_visible_mounts(std::string fuse_conf_path) {
  std::ifstream input(fuse_conf_path);

  std::string line;
  while (std::getline(input, line)) {
    if (line == "user_allow_other") {
      return true;
    }
  }

  return false;
}

static const char kDefaultMountRoot[] = "/mnt/xarfuse";

std::vector<std::string> tools::xar::default_mount_roots() {
  return {kDefaultMountRoot, "/dev/shm"};
}

void tools::xar::no_mount_roots_help_message(std::ostream& out) {
  out << "Unable to find suitabe 01777 mount root. Try: mkdir "
      << kDefaultMountRoot << " && chmod 01777 " << kDefaultMountRoot;
}
