// Copyright 2004-present Facebook. All Rights Reserved.

#include <algorithm>

#include "XarParser.h"

namespace tools {
namespace xar {

XarParserError::XarParserError(
    XarParserErrorType type,
    const std::string& detail) noexcept
    : type_(type), detail_(detail) {}

XarParserError::XarParserError(XarParserErrorType type) noexcept
    : XarParserError(type, "") {}

XarParserErrorType XarParserError::type() const noexcept {
  return type_;
}

std::string XarParserError::getErrorMessage() const noexcept {
  const auto getBaseMessage = [](const auto& t) {
    switch (t) {
      case XarParserErrorType::DUPLICATE_PARAMETER:
        return "Variable is assigned more than once: ";
      case XarParserErrorType::FILE_OPEN:
        return "Failed to open file for reading: ";
      case XarParserErrorType::FILE_READ:
        return "Failed to read file: ";
      case XarParserErrorType::INCORRECT_MAGIC:
        return "Incorrect squashfs magic";
      case XarParserErrorType::INVALID_OFFSET:
        return "Invalid offset: ";
      case XarParserErrorType::INVALID_SHEBANG:
        return "Invalid shebang: ";
      case XarParserErrorType::MALFORMED_LINE:
        return "Failed to parse line: ";
      case XarParserErrorType::MISSING_PARAMETERS:
        return "Missing required parameters: ";
      case XarParserErrorType::TRAMPOLINE_ERROR:
        return "Error parsing trampoline names: ";
      case XarParserErrorType::UNEXPECTED_END_OF_FILE:
        return "Unexpected end of file reached: ";
    }
  };
  return getBaseMessage(type_) + detail_;
}

XarParserResult::XarParserResult(XarHeader xarHeader) noexcept
    : valueOrError_(xarHeader) {}

XarParserResult::XarParserResult(XarParserError xarParserError) noexcept
    : valueOrError_(xarParserError) {}

bool XarParserResult::hasError() const noexcept {
  return std::holds_alternative<XarParserError>(valueOrError_);
}

XarParserError XarParserResult::error() const {
  return std::get<XarParserError>(valueOrError_);
}

bool XarParserResult::hasValue() const noexcept {
  return std::holds_alternative<XarHeader>(valueOrError_);
}

XarHeader XarParserResult::value() const {
  return std::get<XarHeader>(valueOrError_);
}

} // namespace xar
} // namespace tools
