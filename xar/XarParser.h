// Copyright 2004-present Facebook. All Rights Reserved.

#include <set>
#include <string>
#include <variant>
#include <vector>

#include "XarHelpers.h"

namespace tools {
namespace xar {

// Error type returned by XAR parser
enum class XarParserErrorType {
  DUPLICATE_PARAMETER,
  FILE_OPEN,
  FILE_READ,
  INCORRECT_MAGIC,
  INVALID_OFFSET,
  INVALID_SHEBANG,
  MALFORMED_LINE,
  MISSING_PARAMETERS,
  TRAMPOLINE_ERROR,
  UNEXPECTED_END_OF_FILE,
};

// Error returned by XAR parser including an error message
class XarParserError {
 public:
  explicit XarParserError(
      XarParserErrorType type,
      const std::string& detail) noexcept;

  explicit XarParserError(XarParserErrorType type) noexcept;

  XarParserErrorType type() const noexcept;

  std::string getErrorMessage() const noexcept;

 private:
  const XarParserErrorType type_;
  const std::string detail_;
};

// Output from XAR parser containing either a representation of a XAR header or
// an error.
class XarParserResult {
 public:
  explicit XarParserResult(XarHeader xarHeader) noexcept;

  explicit XarParserResult(XarParserError xarParserError) noexcept;

  bool hasError() const noexcept;

  XarParserError error() const;

  bool hasValue() const noexcept;

  XarHeader value() const;

 private:
  const std::variant<XarHeader, XarParserError> valueOrError_;
};

namespace detail {

// Parse a single NAME="value" line from the header and set the provided
// XarHeader and set of names found appropriately.
std::optional<XarParserError> parseLine(
    const std::string& line,
    XarHeader* xarHeader,
    std::set<std::string>* foundNames);

// squashfs magic is required to be at the start of a squashfs image (i.e. at
// offset in xar)
constexpr uint8_t kSquashfsMagic[] = {0x68, 0x73, 0x71, 0x73};

} // namespace detail

// Returns the header of XAR if and only if fd points to a file beginning with a
// valid XAR header. This does not verify that the rest of the xar is valid
// (e.g. squashfs image is mountable, xarexec_target and trampolines exist).
XarParserResult parseXarHeader(int fd) noexcept;

// Returns the header of XAR if and only if xar_path points to a file beginning
// with a valid XAR header. This does not verify that the rest of the xar is
// valid (e.g. that squashfs image is mountable, xaraexec_target and trampolines
// exist).
XarParserResult parseXarHeader(const std::string& xar_path) noexcept;

} // namespace xar
} // namespace tools
