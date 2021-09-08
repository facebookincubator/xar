// Copyright 2004-present Facebook. All Rights Reserved.

#include <string>
#include <variant>
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
} // namespace xar
} // namespace tools