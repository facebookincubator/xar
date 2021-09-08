// Copyright 2004-present Facebook. All Rights Reserved.

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include "XarHelpers.h"
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

TEST(XarParserParseLineTest, TestParseWithMissingEqual) {
  XarHeader header;
  std::set<std::string> foundNames{};
  auto res = detail::parseLine(u8R"(OFFSET "")", &header, &foundNames);
  ASSERT_TRUE(res.has_value());
  EXPECT_EQ(res.value().type(), XarParserErrorType::MALFORMED_LINE)
      << res.value().getErrorMessage();
}

TEST(XarParserParseLineTest, TestParseWithMissingDoubleQuotes) {
  { // No " instead of two
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(u8R"(OFFSET=)", &header, &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::MALFORMED_LINE)
        << res.value().getErrorMessage();
    ;
  }
  { // Only one " instead of two
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(u8R"(OFFSET=")", &header, &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::MALFORMED_LINE)
        << res.value().getErrorMessage();
    ;
  }
}

TEST(XarParserParseLineTest, TestParseWithQuoteInValue) {
  XarHeader header;
  std::set<std::string> foundNames{};
  auto res = detail::parseLine(
      u8R"(XAREXEC_TRAMPOLINE_NAMES=""")", &header, &foundNames);
  ASSERT_TRUE(res.has_value());
  EXPECT_EQ(res.value().type(), XarParserErrorType::MALFORMED_LINE)
      << res.value().getErrorMessage();
}

TEST(XarParserParseLineTest, TestParseDuplicateName) {
  XarHeader header;
  std::set<std::string> foundNames{"OFFSET"};
  auto res = detail::parseLine(u8R"(OFFSET="4096")", &header, &foundNames);
  ASSERT_TRUE(res.has_value());
  EXPECT_EQ(res.value().type(), XarParserErrorType::DUPLICATE_PARAMETER)
      << res.value().getErrorMessage();
}

TEST(XarParserParseLineTest, TestParseWithEmptyName) {
  XarHeader header;
  std::set<std::string> foundNames{};
  auto res = detail::parseLine(u8R"(="val")", &header, &foundNames);
  ASSERT_TRUE(res.has_value());
  EXPECT_EQ(res.value().type(), XarParserErrorType::MALFORMED_LINE)
      << res.value().getErrorMessage();
}

TEST(XarParserParseLineTest, TestParseWithUnknownName) {
  // We should not fail if a new variable is introduced
  XarHeader header;
  std::set<std::string> foundNames{};
  auto res = detail::parseLine(u8R"(NEW_NAME="1234")", &header, &foundNames);
  ASSERT_FALSE(res.has_value());
}

TEST(XarParserParseLineTest, TestParseOffset) {
  { // Typical
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(u8R"(OFFSET="4096")", &header, &foundNames);
    EXPECT_FALSE(res.has_value()) << res.value().getErrorMessage();
    EXPECT_EQ(header.offset, 4096);
  }
  { // Positive multiple of 4096 (that's not 4096)
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(u8R"(OFFSET="8192")", &header, &foundNames);
    EXPECT_FALSE(res.has_value()) << res.value().getErrorMessage();
    EXPECT_EQ(header.offset, 8192);
  }
  { // Empty value
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(u8R"(OFFSET="")", &header, &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::INVALID_OFFSET);
    EXPECT_EQ(
        res.value().getErrorMessage(),
        "Invalid offset: Cannot be parsed as an unsigned integer");
  }
  { // Can't be parsed as unsigned int
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(u8R"(OFFSET="4096X")", &header, &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::INVALID_OFFSET);
    EXPECT_EQ(
        res.value().getErrorMessage(),
        "Invalid offset: Cannot be parsed as an unsigned integer");
  }
  { // Out of range
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(OFFSET="999999999999999999999")", &header, &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::INVALID_OFFSET);
    EXPECT_EQ(res.value().getErrorMessage(), "Invalid offset: Out of range");
  }
  { // Not a positive multiple of 4096
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(u8R"(OFFSET="1234")", &header, &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::INVALID_OFFSET);
    EXPECT_EQ(
        res.value().getErrorMessage(),
        "Invalid offset: 1234 is not a positive multiple of 4096");
  }
}

TEST(XarParserParseLineTest, TestParseSimpleParameters) {
  XarHeader header;
  std::set<std::string> foundNames{};
  {
    auto res =
        detail::parseLine(u8R"(VERSION="1624969851")", &header, &foundNames);
    EXPECT_FALSE(res.has_value()) << res.value().getErrorMessage();
  }
  {
    auto res = detail::parseLine(u8R"(UUID="d770950c")", &header, &foundNames);
    EXPECT_FALSE(res.has_value()) << res.value().getErrorMessage();
  }
  EXPECT_THAT(foundNames, ::testing::UnorderedElementsAre(kVersion, kUuidName));
  EXPECT_EQ(header.version, "1624969851");
  EXPECT_EQ(header.uuid, "d770950c");
}

TEST(XarParserParseLineTest, TestParseTrampolineNames) {
  { // Single name
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="'invoke_xar_via_trampoline'")",
        &header,
        &foundNames);
    EXPECT_FALSE(res.has_value()) << res.value().getErrorMessage();
    EXPECT_THAT(
        header.xarexecTrampolineNames,
        ::testing::UnorderedElementsAre("invoke_xar_via_trampoline"));
    EXPECT_TRUE(foundNames.find(kXarexecTrampolineNames) != foundNames.end());
  }
  { // Multiple names. This tests cases where {' ', '\\', '='} are in names.
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="'invoke_xar_via_trampoline' ' tramp 1 ' 'tramp\2' 'tramp=3'")",
        &header,
        &foundNames);
    EXPECT_FALSE(res.has_value()) << res.value().getErrorMessage();
    EXPECT_THAT(
        header.xarexecTrampolineNames,
        ::testing::UnorderedElementsAre(
            "invoke_xar_via_trampoline", " tramp 1 ", "tramp\\2", "tramp=3"));
    EXPECT_TRUE(foundNames.find(kXarexecTrampolineNames) != foundNames.end());
  }
  { // Case with single space as trampoline name
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="' ' 'invoke_xar_via_trampoline'")",
        &header,
        &foundNames);
    EXPECT_FALSE(res.has_value()) << res.value().getErrorMessage();
    EXPECT_THAT(
        header.xarexecTrampolineNames,
        ::testing::UnorderedElementsAre("invoke_xar_via_trampoline", " "));
    EXPECT_TRUE(foundNames.find(kXarexecTrampolineNames) != foundNames.end());
  }
  { // Empty.
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="")", &header, &foundNames);
    EXPECT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
  { // Empty trampoline name
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="''")", &header, &foundNames);
    EXPECT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
  { // Single name but with unexpected space at front
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES=" 'invoke_xar_via_trampoline'")",
        &header,
        &foundNames);
    EXPECT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
  { // Single name but with unexpected space at end
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="'invoke_xar_via_trampoline' ")",
        &header,
        &foundNames);
    EXPECT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
  { // Missing required name
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="'tramp'")", &header, &foundNames);
    EXPECT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
  { // Single quote in name
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="'invoke_xar_via_'trampoline' 'tramp'")",
        &header,
        &foundNames);
    EXPECT_TRUE(res.has_value()) << res.value().getErrorMessage();
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
  { // Extra spaces fails
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="'invoke_xar_via_trampoline'  'tramp'")",
        &header,
        &foundNames);
    EXPECT_TRUE(res.has_value()) << res.value().getErrorMessage();
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
  { // No space separating names
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="'invoke_xar_via_trampoline''tramp'")",
        &header,
        &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
  { // Unclosed quote
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = detail::parseLine(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="'invoke_xar_via_trampoline")",
        &header,
        &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
}

} // namespace xar
} // namespace tools
