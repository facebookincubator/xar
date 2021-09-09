// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#include "XarHelpers.h"

#include <gtest/gtest.h>

using namespace std;
using namespace tools::xar;

// Tests stolen, and minimally adapted, from folly/test/StringTest.cpp

TEST(XarHelpers, SplitTest) {
  vector<string> parts;

  parts = split(',', "a,b,c");
  EXPECT_EQ(parts.size(), 3);
  EXPECT_EQ(parts[0], "a");
  EXPECT_EQ(parts[1], "b");
  EXPECT_EQ(parts[2], "c");
  parts.clear();

  parts = split(',', "a,,c");
  EXPECT_EQ(parts.size(), 3);
  EXPECT_EQ(parts[0], "a");
  EXPECT_EQ(parts[1], "");
  EXPECT_EQ(parts[2], "c");
  parts.clear();

  parts = split("a", "");
  EXPECT_EQ(parts.size(), 1);
  EXPECT_EQ(parts[0], "");
  parts.clear();

  parts = split("a", "abcdefg");
  EXPECT_EQ(parts.size(), 2);
  EXPECT_EQ(parts[0], "");
  EXPECT_EQ(parts[1], "bcdefg");
  parts.clear();

  string orig = "All, your base, are , belong to us";
  parts = split(", ", orig);
  EXPECT_EQ(parts.size(), 4);
  EXPECT_EQ(parts[0], "All");
  EXPECT_EQ(parts[1], "your base");
  EXPECT_EQ(parts[2], "are ");
  EXPECT_EQ(parts[3], "belong to us");
  parts.clear();

  orig = ", Facebook, rul,es!, ";
  parts = split(", ", orig);
  EXPECT_EQ(parts.size(), 4);
  EXPECT_EQ(parts[0], "");
  EXPECT_EQ(parts[1], "Facebook");
  EXPECT_EQ(parts[2], "rul,es!");
  EXPECT_EQ(parts[3], "");
  parts.clear();
  parts = split(", ", orig);
  EXPECT_EQ(parts.size(), 4);
  EXPECT_EQ(parts[0], "");
  EXPECT_EQ(parts[1], "Facebook");
  EXPECT_EQ(parts[2], "rul,es!");
  EXPECT_EQ(parts[3], "");
}

TEST(XarHelpers, PartialSplitTest) {
  vector<string> parts;

  parts = split(",", "a,b,c", 0);
  EXPECT_EQ(parts.size(), 1);
  EXPECT_EQ(parts[0], "a,b,c");

  parts = split(",", "a,b,c", 1);
  EXPECT_EQ(parts.size(), 2);
  EXPECT_EQ(parts[0], "a");
  EXPECT_EQ(parts[1], "b,c");

  parts = split(",", "a,b,c", 2);
  EXPECT_EQ(parts.size(), 3);
  EXPECT_EQ(parts[0], "a");
  EXPECT_EQ(parts[1], "b");
  EXPECT_EQ(parts[2], "c");

  parts = split(",", "a,b,c", 99);
  EXPECT_EQ(parts.size(), 3);
  EXPECT_EQ(parts[0], "a");
  EXPECT_EQ(parts[1], "b");
  EXPECT_EQ(parts[2], "c");

  // Test case for XAR headers
  parts = split("=", "XAR_HEADER=\"a=b=c\"", 1);
  EXPECT_EQ(parts.size(), 2);
  EXPECT_EQ(parts[0], "XAR_HEADER");
  EXPECT_EQ(parts[1], "\"a=b=c\"");
}

TEST(XarHelpers, JoinTest) {
  std::string joined = join(",", std::vector<std::string>{"a", "b", "c", "d"});
  EXPECT_EQ(joined, "a,b,c,d");

  joined = join(
      ", ", std::vector<std::string>{"All", "your base are", "belong to us"});
  EXPECT_EQ(joined, "All, your base are, belong to us");

  joined = join(",", std::vector<std::string>{"One item"});
  EXPECT_EQ(joined, "One item");

  joined = join(",", std::vector<std::string>{});
  EXPECT_EQ(joined, "");
}

TEST(XarHelpers, FuseConfTest) {
  // Test two normal-ish fuse.conf examples.
  EXPECT_TRUE(
      fuse_allows_visible_mounts("tools/xar/fuse_conf_with_user_allow_other"));
  EXPECT_FALSE(fuse_allows_visible_mounts(
      "tools/xar/fuse_conf_without_user_allow_other"));

  // Test some corner cases -- missing and empty files.
  EXPECT_FALSE(fuse_allows_visible_mounts("/dev/null"));
  EXPECT_FALSE(fuse_allows_visible_mounts("/dev/null/not/a/valid/path"));
}

TEST(XarHelpers, DefaultMountRootsTest) {
  const auto mount_roots = default_mount_roots();
  EXPECT_FALSE(mount_roots.empty());
  const std::string expected = "/mnt/xarfuse";
  bool found_expected = false;
  for (const auto& mount_root : mount_roots) {
    if (mount_root == expected) {
      found_expected = true;
      break;
    }
  }
  EXPECT_TRUE(found_expected);
}

TEST(XarHelpers, FindCgroupInodeTest) {
  const auto present_cgroup_inode =
      tools::xar::read_sysfs_cgroup_inode("/proc/self/cgroup");
  EXPECT_TRUE(present_cgroup_inode);
  const auto missing_cgroup_inode =
      tools::xar::read_sysfs_cgroup_inode("/doesnotexistlalalala");
  EXPECT_FALSE(missing_cgroup_inode);
}

TEST(XarHelpers, SerializeHeaderAsJSONTest) {
  const XarHeader header{
      .offset = 4096,
      .uuid = "d770950c",
      .version = "1628211316",
      .xarexecTarget = "xar_bootstrap.sh",
      .xarexecTrampolineNames = {"lookup.xar", "invoke_xar_via_trampoline"},
  };
  const auto json = serializeHeaderAsJSON(header);
  EXPECT_EQ(
      json,
      R"({"OFFSET":4096,"UUID":"d770950c","VERSION":"1628211316","XAREXEC_TARGET":"xar_bootstrap.sh","XAREXEC_TRAMPOLINE_NAMES":["lookup.xar","invoke_xar_via_trampoline"]})");
}
