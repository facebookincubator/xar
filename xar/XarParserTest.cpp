// Copyright 2004-present Facebook. All Rights Reserved.

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <filesystem>

#include "FileUtil.h"
#include "XarHelpers.h"
#include "XarParser.h"

namespace tools {
namespace xar {

#define PARSELINE(s, h, n) \
  detail::parseLine(reinterpret_cast<const char*>(s), h, n)

constexpr auto kTestHeaderSize = 4096;

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
  auto res = PARSELINE(u8R"(OFFSET "")", &header, &foundNames);
  ASSERT_TRUE(res.has_value());
  EXPECT_EQ(res.value().type(), XarParserErrorType::MALFORMED_LINE)
      << res.value().getErrorMessage();
}

TEST(XarParserParseLineTest, TestParseWithMissingDoubleQuotes) {
  { // No " instead of two
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = PARSELINE(u8R"(OFFSET=)", &header, &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::MALFORMED_LINE)
        << res.value().getErrorMessage();
    ;
  }
  { // Only one " instead of two
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = PARSELINE(u8R"(OFFSET=")", &header, &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::MALFORMED_LINE)
        << res.value().getErrorMessage();
    ;
  }
}

TEST(XarParserParseLineTest, TestParseWithQuoteInValue) {
  XarHeader header;
  std::set<std::string> foundNames{};
  auto res =
      PARSELINE(u8R"(XAREXEC_TRAMPOLINE_NAMES=""")", &header, &foundNames);
  ASSERT_TRUE(res.has_value());
  EXPECT_EQ(res.value().type(), XarParserErrorType::MALFORMED_LINE)
      << res.value().getErrorMessage();
}

TEST(XarParserParseLineTest, TestParseDuplicateName) {
  XarHeader header;
  std::set<std::string> foundNames{"OFFSET"};
  auto res = PARSELINE(u8R"(OFFSET="4096")", &header, &foundNames);
  ASSERT_TRUE(res.has_value());
  EXPECT_EQ(res.value().type(), XarParserErrorType::DUPLICATE_PARAMETER)
      << res.value().getErrorMessage();
}

TEST(XarParserParseLineTest, TestParseWithEmptyName) {
  XarHeader header;
  std::set<std::string> foundNames{};
  auto res = PARSELINE(u8R"(="val")", &header, &foundNames);
  ASSERT_TRUE(res.has_value());
  EXPECT_EQ(res.value().type(), XarParserErrorType::MALFORMED_LINE)
      << res.value().getErrorMessage();
}

TEST(XarParserParseLineTest, TestParseWithUnknownName) {
  // We should not fail if a new variable is introduced
  XarHeader header;
  std::set<std::string> foundNames{};
  auto res = PARSELINE(u8R"(NEW_NAME="1234")", &header, &foundNames);
  ASSERT_FALSE(res.has_value());
}

TEST(XarParserParseLineTest, TestParseOffset) {
  { // Typical
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = PARSELINE(u8R"(OFFSET="4096")", &header, &foundNames);
    EXPECT_FALSE(res.has_value()) << res.value().getErrorMessage();
    EXPECT_EQ(header.offset, 4096);
  }
  { // Positive multiple of 4096 (that's not 4096)
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = PARSELINE(u8R"(OFFSET="8192")", &header, &foundNames);
    EXPECT_FALSE(res.has_value()) << res.value().getErrorMessage();
    EXPECT_EQ(header.offset, 8192);
  }
  { // Empty value
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = PARSELINE(u8R"(OFFSET="")", &header, &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::INVALID_OFFSET);
    EXPECT_EQ(
        res.value().getErrorMessage(),
        "Invalid offset: Cannot be parsed as an unsigned integer");
  }
  { // Can't be parsed as unsigned int
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = PARSELINE(u8R"(OFFSET="4096X")", &header, &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::INVALID_OFFSET);
    EXPECT_EQ(
        res.value().getErrorMessage(),
        "Invalid offset: Cannot be parsed as an unsigned integer");
  }
  { // Out of range
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res =
        PARSELINE(u8R"(OFFSET="999999999999999999999")", &header, &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::INVALID_OFFSET);
    EXPECT_EQ(res.value().getErrorMessage(), "Invalid offset: Out of range");
  }
  { // Not a positive multiple of 4096
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = PARSELINE(u8R"(OFFSET="1234")", &header, &foundNames);
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
    auto res = PARSELINE(u8R"(VERSION="1624969851")", &header, &foundNames);
    EXPECT_FALSE(res.has_value()) << res.value().getErrorMessage();
  }
  {
    auto res = PARSELINE(u8R"(UUID="d770950c")", &header, &foundNames);
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
    auto res = PARSELINE(
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
    auto res = PARSELINE(
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
    auto res = PARSELINE(
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
    auto res =
        PARSELINE(u8R"(XAREXEC_TRAMPOLINE_NAMES="")", &header, &foundNames);
    EXPECT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
  { // Empty trampoline name
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res =
        PARSELINE(u8R"(XAREXEC_TRAMPOLINE_NAMES="''")", &header, &foundNames);
    EXPECT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
  { // Single name but with unexpected space at front
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = PARSELINE(
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
    auto res = PARSELINE(
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
    auto res = PARSELINE(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="'tramp'")", &header, &foundNames);
    EXPECT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
  { // Single quote in name
    XarHeader header;
    std::set<std::string> foundNames{};
    auto res = PARSELINE(
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
    auto res = PARSELINE(
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
    auto res = PARSELINE(
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
    auto res = PARSELINE(
        u8R"(XAREXEC_TRAMPOLINE_NAMES="'invoke_xar_via_trampoline")",
        &header,
        &foundNames);
    ASSERT_TRUE(res.has_value());
    EXPECT_EQ(res.value().type(), XarParserErrorType::TRAMPOLINE_ERROR)
        << res.value().getErrorMessage();
  }
}

class SelfClosingFdHolder {
 public:
  explicit SelfClosingFdHolder(int fd) : fd_{fd} {}
  ~SelfClosingFdHolder() {
    if (fd_ != -1) {
      tools::xar::closeNoInt(fd_);
    }
  }
  const int fd_;
};

class XarParserTest : public ::testing::Test {
 protected:
  // Create a temporary file with a given XAR header with squashfs magic added.
  void makeXar(const char* header) {
    makeXar(
        header,
        /* includeMagic */ true,
        /* magic */
        std::vector(kSquashfsMagic, kSquashfsMagic + sizeof(kSquashfsMagic)));
  }
#if __cplusplus > 201703L // C++20 or newer
  void makeXar(const char8_t* header) {
    makeXar(reinterpret_cast<const char*>(header));
  }
  void makeXar(
      const char8_t* header,
      bool includeMagic,
      const std::vector<uint8_t>& magic) {
    makeXar(reinterpret_cast<const char*>(header), includeMagic, magic);
  }
#endif

  // Create a temporary file with a given XAR header.
  //
  // If includeMagic is set, the file will be padded to the test header size
  // bytes and squashfs magic will be added. If includeMagic and wrongMagic are
  // set, the file will be padded and squashfs magic will be incorrectly set.
  void makeXar(
      const std::string& header,
      bool includeMagic,
      const std::vector<uint8_t>& magic) {
    const auto filenameTemplate = std::filesystem::temp_directory_path()
                                      .append("test_xar_headerXXXXXX")
                                      .string();
    char* filename = new char[filenameTemplate.size() + 1];
    ::strncpy(filename, filenameTemplate.c_str(), filenameTemplate.size() + 1);
    fdHolder_ = std::make_unique<SelfClosingFdHolder>(::mkstemp(filename));
    ASSERT_GE(fdHolder_->fd_, 0) << "Failed to make temporary file" << errno;
    // Delete the temp file later on ::close
    ::unlink(filename);

    int bytes;
    if (includeMagic) {
      char buf[kTestHeaderSize + magic.size() + 1];
      memset(buf, 0, sizeof(buf));
      EXPECT_LE(header.size(), kTestHeaderSize);
      ::strncpy(buf, header.c_str(), sizeof(buf));
      ::memcpy(&buf[kTestHeaderSize], magic.data(), magic.size());
      bytes = tools::xar::writeFull(fdHolder_->fd_, buf, sizeof(buf));
      ASSERT_EQ(bytes, sizeof(buf));
    } else {
      bytes =
          tools::xar::writeFull(fdHolder_->fd_, header.c_str(), header.size());
      ASSERT_EQ(bytes, header.size());
    }
  }

  int getFd() {
    return fdHolder_->fd_;
  }

 private:
  std::unique_ptr<SelfClosingFdHolder> fdHolder_;
};

TEST_F(XarParserTest, TestValidHeader) {
  makeXar(
      u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="4096"
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
XAREXEC_TRAMPOLINE_NAMES="'lookup.xar' 'invoke_xar_via_trampoline'"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at 4096)");
  const auto maybeHeader = parseXarHeader(getFd());
  ASSERT_FALSE(maybeHeader.hasError()) << maybeHeader.error().getErrorMessage();
  EXPECT_EQ(maybeHeader.value().offset, 4096);
  EXPECT_EQ(maybeHeader.value().uuid, "d770950c");
  EXPECT_EQ(maybeHeader.value().version, "1624969851");
  EXPECT_EQ(maybeHeader.value().xarexecTarget, "xar_bootstrap.sh");
  EXPECT_THAT(
      maybeHeader.value().xarexecTrampolineNames,
      ::testing::UnorderedElementsAre(
          "lookup.xar", "invoke_xar_via_trampoline"));
}

TEST_F(XarParserTest, TestValidHeaderWithoutNonRequired) {
  makeXar(
      u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="4096"
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at 4096)");
  const auto maybeHeader = parseXarHeader(getFd());
  ASSERT_FALSE(maybeHeader.hasError()) << maybeHeader.error().getErrorMessage();
  EXPECT_EQ(maybeHeader.value().offset, 4096);
  EXPECT_EQ(maybeHeader.value().uuid, "d770950c");
  EXPECT_EQ(maybeHeader.value().version, "1624969851");
  EXPECT_EQ(maybeHeader.value().xarexecTarget, "xar_bootstrap.sh");
  EXPECT_TRUE(maybeHeader.value().xarexecTrampolineNames.empty());
}

TEST_F(XarParserTest, TestInvalidHeaderInvalidShebang) {
  makeXar(
      u8R"(#!invalid
OFFSET="4096"
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at 4096)");
  const auto maybeHeader = parseXarHeader(getFd());
  ASSERT_TRUE(maybeHeader.hasError());
  EXPECT_EQ(maybeHeader.error().type(), XarParserErrorType::INVALID_SHEBANG)
      << maybeHeader.error().getErrorMessage();
}

TEST_F(XarParserTest, TestInvalidHeaderMalformedLine) {
  { // Missing " for OFFSET
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
OFFSET=4096
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at 4096)");
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(maybeHeader.error().type(), XarParserErrorType::MALFORMED_LINE)
        << maybeHeader.error().getErrorMessage();
  }
  { // " in UUID value when there should never be " in values
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="4096"
UUID="d"770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at 4096)");
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(maybeHeader.error().type(), XarParserErrorType::MALFORMED_LINE)
        << maybeHeader.error().getErrorMessage();
  }
}

TEST_F(XarParserTest, TestInvalidHeaderInvalidOffset) {
  { // Fail to parse as integer
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="<not a number>"
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at <not a number>)");
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(maybeHeader.error().type(), XarParserErrorType::INVALID_OFFSET)
        << maybeHeader.error().getErrorMessage();
  }
  { // Out of range
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="999999999999999999999"
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at <not a number>)");
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(maybeHeader.error().type(), XarParserErrorType::INVALID_OFFSET)
        << maybeHeader.error().getErrorMessage();
  }
  { // Offset not a multiple of 4096
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="1234"
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at <not a number>)");
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(maybeHeader.error().type(), XarParserErrorType::INVALID_OFFSET)
        << maybeHeader.error().getErrorMessage();
  }
  { // Offset greater than max header size we read (kMaxHeaderSize)
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="16384"
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at 16384)");
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(maybeHeader.error().type(), XarParserErrorType::INVALID_OFFSET)
        << maybeHeader.error().getErrorMessage();
  }
}

TEST_F(XarParserTest, TestInvalidHeaderDuplicateParameter) {
  makeXar(
      u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="4096"
OFFSET="4096"
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at 4096)");
  const auto maybeHeader = parseXarHeader(getFd());
  ASSERT_TRUE(maybeHeader.hasError());
  EXPECT_EQ(maybeHeader.error().type(), XarParserErrorType::DUPLICATE_PARAMETER)
      << maybeHeader.error().getErrorMessage();
}

TEST_F(XarParserTest, TestInvalidHeaderMissingParameter) {
  { // Missing offset
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at 4096)");
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(
        maybeHeader.error().type(), XarParserErrorType::MISSING_PARAMETERS)
        << maybeHeader.error().getErrorMessage();
  }
  { // Missing some other parameter
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="4096"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at 4096)");
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(
        maybeHeader.error().type(), XarParserErrorType::MISSING_PARAMETERS)
        << maybeHeader.error().getErrorMessage();
  }
}

TEST_F(XarParserTest, TestInvalidHeaderWithIncorrectMagic) {
  static_assert(sizeof(kSquashfsMagic) == 4);
  { // First byte wrong
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="4096"
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at 4096)",
        /* includeMagic */ true,
        /* magic */
        {0xFF, kSquashfsMagic[1], kSquashfsMagic[2], kSquashfsMagic[3]});
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(maybeHeader.error().type(), XarParserErrorType::INCORRECT_MAGIC)
        << maybeHeader.error().getErrorMessage();
  }
  { // Correct but misaligned
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="4096"
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
DEPENDENCIES=""
#xar_stop
echo This XAR file should not be executed by sh
exit 1
# Actual squashfs file begins at 4096)",
        /* includeMagic */ false,
        {0xFF, kSquashfsMagic[0], kSquashfsMagic[1], kSquashfsMagic[2]});
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(maybeHeader.error().type(), XarParserErrorType::INCORRECT_MAGIC)
        << maybeHeader.error().getErrorMessage();
  }
}

TEST_F(XarParserTest, TestInvalidHeaderEmptyFile) {
  makeXar("", /* includeMagic */ false, /* magic */ {});
  const auto maybeHeader = parseXarHeader(getFd());
  ASSERT_TRUE(maybeHeader.hasError());
  EXPECT_EQ(maybeHeader.error().type(), XarParserErrorType::FILE_READ)
      << maybeHeader.error().getErrorMessage();
}

TEST_F(XarParserTest, TestInvalidHeaderUnexpectedEndOfFile) {
  { // Fail to read offset line
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse)",
        /* includeMagic */ false,
        /* magic */ {});
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(
        maybeHeader.error().type(), XarParserErrorType::UNEXPECTED_END_OF_FILE)
        << maybeHeader.error().getErrorMessage();
  }
  { // Fail to read another line
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="4096")",
        /* includeMagic */ false,
        /* magic */ {});
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(
        maybeHeader.error().type(), XarParserErrorType::UNEXPECTED_END_OF_FILE)
        << maybeHeader.error().getErrorMessage();
  }
  { // Have all required variables but missing #xar_stop
    makeXar(
        u8R"(#!/usr/bin/env xarexec_fuse
OFFSET="4096"
UUID="d770950c"
VERSION="1624969851"
XAREXEC_TARGET="xar_bootstrap.sh"
XAREXEC_TRAMPOLINE_NAMES="'lookup.xar' 'invoke_xar_via_trampoline'"
DEPENDENCIES="")",
        /* includeMagic */ false,
        /* magic */ {});
    const auto maybeHeader = parseXarHeader(getFd());
    ASSERT_TRUE(maybeHeader.hasError());
    EXPECT_EQ(
        maybeHeader.error().type(), XarParserErrorType::UNEXPECTED_END_OF_FILE)
        << maybeHeader.error().getErrorMessage();
  }
}

TEST_F(XarParserTest, TestInvalidXarParserErrorType) {
  // create an error with an invalid XarParserErrorType
  const auto xarError = XarParserError((XarParserErrorType)-1);
  EXPECT_EQ(xarError.getErrorMessage(), "Unknown XarParserErrorType");
}

} // namespace xar
} // namespace tools
