// Copyright 2004-present Facebook.  All rights reserved.
//
// Helper functions; mainly here to make it testable rather than for
// actual re-use.

#pragma once

#include <fcntl.h>
#include <unistd.h>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

// Inspired by glog's CHECK/PCHECK, these macros don't rely on glog
// itself, which we intentionally avoid due to issues using it in a
// setuid context.
#define CHECK_SIMPLE(test)               \
  do {                                   \
    if (!(test)) {                       \
      try {                              \
        std::cerr << #test << std::endl; \
      } catch (...) {                    \
      }                                  \
      abort();                           \
    }                                    \
  } while (0)
#define PCHECK_SIMPLE(test)                                         \
  do {                                                              \
    if (!(test)) {                                                  \
      try {                                                         \
        std::cerr << #test << ": " << strerror(errno) << std::endl; \
      } catch (...) {                                               \
      }                                                             \
      abort();                                                      \
    }                                                               \
  } while (0)

namespace tools {
namespace xar {

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
}

// A slow, simple split function.
template <typename DelimType>
std::vector<std::string> split(const DelimType& delim, std::string s) {
  std::vector<std::string> ret;

  while (true) {
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
}
}
