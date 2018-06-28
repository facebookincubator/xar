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
