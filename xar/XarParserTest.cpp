// Copyright 2004-present Facebook. All Rights Reserved.

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include "XarParser.h"

namespace tools {
namespace xar {

TEST(XarParserResultTest, TestXarParserResultError) {
  auto res = XarParserResult(
      XarParserError(XarParserErrorType::DUPLICATE_PARAMETER, "VAR"));
  ASSERT_TRUE(res.hasError());
  ASSERT_FALSE(res.hasValue());
  EXPECT_EQ(res.error().type(), XarParserErrorType::DUPLICATE_PARAMETER);
  EXPECT_EQ(
      res.error().getErrorMessage(),
      "Variable is assigned more than once: VAR");
  EXPECT_THROW(res.value(), std::bad_variant_access);
}

TEST(XarParserResultTest, TestXarParserResultSuccess) {
  auto header = XarHeader{
      .offset = 4096,
      .uuid = "d770950c",
      .version = "1628211316",
      .xarexecTarget = "xar_bootstrap.sh",
      .xarexecTrampolineNames = {"lookup.xar", "invoke_xar_via_trampoline"},
  };
  auto res = XarParserResult(header);
  ASSERT_FALSE(res.hasError());
  ASSERT_TRUE(res.hasValue());
  EXPECT_EQ(res.value().offset, header.offset);
  EXPECT_EQ(res.value().uuid, header.uuid);
  EXPECT_EQ(res.value().version, header.version);
  EXPECT_EQ(res.value().xarexecTarget, header.xarexecTarget);
  EXPECT_THAT(
      res.value().xarexecTrampolineNames,
      ::testing::UnorderedElementsAre(
          "lookup.xar", "invoke_xar_via_trampoline"));
  EXPECT_THROW(res.error(), std::bad_variant_access);
}

} // namespace xar
} // namespace tools
