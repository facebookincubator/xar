// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.
//
// Helper functions; mainly here to make it testable rather than for
// actual re-use.

#pragma once

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace tools {
namespace xar {

// Representation of XAR header found at the top of any XAR file
struct XarHeader {
  unsigned long long offset;
  std::string uuid;
  std::string version;
  std::string xarexecTarget;
  // List of trampoline names. These are not shell-escaped and so may differ
  // from the original shell-escaped names in the header.
  std::vector<std::string> xarexecTrampolineNames;
};

// The unmount command used for unmounting the squash fs. Differs depending on
// OS.
extern const char* UNMOUNT_CMD;

namespace {
size_t delimSize(char) {
  return 1;
}
size_t delimSize(const std::string& s) {
  return s.size();
}
} // namespace

// A slow, simple split function.  nsplits behaves like Python's split
// function.
template <typename DelimType>
std::vector<std::string>
split(const DelimType& delim, std::string s, const ssize_t nsplits = -1) {
  std::vector<std::string> ret;

  while (true) {
    if (nsplits > -1 && ret.size() >= nsplits) {
      ret.push_back(s);
      break;
    }

    auto next = s.find(delim);
    if (next == std::string::npos) {
      ret.push_back(s);
      break;
    }

    ret.emplace_back(s.begin(), s.begin() + next);
    s.erase(s.begin(), s.begin() + next + delimSize(delim));
  }

  return ret;
}

// A simple join function that will return `items` joined by `delim`.
template <typename T>
std::string join(const std::string& delim, const T& items) {
  std::string s;
  for (const auto& item : items) {
    if (!s.empty()) {
      s += delim;
    }
    s += item;
  }
  return s;
}

// Return true if the host has enabled "user_allow_other" in
// /etc/fuse.conf.
//
// Takes path as a parameter for testing purposes.
bool fuse_allows_visible_mounts(std::string fuse_conf_path);

// Check if directory is owned by one of the groups the user is in.
bool is_user_in_group(gid_t dir_gid);

// Close all fds that aren't 0, 1, 2
void close_non_std_fds();

// Check if squashfs is mounted.
bool is_squashfs_mounted(const struct statfs& buf);

// Returns the default mount points for XAR.
std::vector<std::string> default_mount_roots();

// Prints a help message for when no mount roots can be found.
void no_mount_roots_help_message(std::ostream& out);

namespace {
// Set to true for verbose output when testing.
constexpr bool debugging = false;
} // namespace

// squashfs magic is required to be at the start of a squashfs image
// (i.e. at offset in XAR)
constexpr uint8_t kSquashfsMagic[] = {0x68, 0x73, 0x71, 0x73};
// Shebang that should be found on the first line of the header
constexpr auto kShebang = "#!/usr/bin/env xarexec_fuse";
// Marker for the end of the header section
constexpr auto kXarStop = "#xar_stop";
// Guaranteed trampoline name if trampoline names header is present
constexpr auto kGuaranteedTrampolineName = "invoke_xar_via_trampoline";

// Header names
constexpr auto kOffsetName = "OFFSET";
constexpr auto kUuidName = "UUID";
constexpr auto kVersion = "VERSION";
constexpr auto kXarexecTarget = "XAREXEC_TARGET";
constexpr auto kXarexecTrampolineNames = "XAREXEC_TRAMPOLINE_NAMES";
constexpr auto kMountRoot = "MOUNT_ROOT";

// Extract the UUID, OFFSET, XAREXEC_TARGET, and other parameters from
// the XAR header.
std::unordered_map<std::string, std::string> read_xar_header(
    const char* filename);

// Attempt to the inode of a cgroup from the contents of a cgroup file
// (typically /proc/PID/cgroup).  This file format is a three field
// colon-separated list defined in cgroups(7).  In practice, the third
// field is what matters which is a path relative to /sys/fs/cgroup
// or, in some FB use cases, relative to /cgroup2.
//
// Typically this function is just passed `/proc/self/cgroup` to find
// this process's cgroup path.
std::optional<ino_t> read_sysfs_cgroup_inode(const char* filename);

// Serialize XAR header an JSON.
std::string serializeHeaderAsJSON(const XarHeader& header) noexcept;

} // namespace xar
} // namespace tools
