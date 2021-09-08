// Copyright 2004-present Facebook. All Rights Reserved.

#include "XarParser.h"
#include "FileUtil.h"
#include "XarHelpers.h"

namespace tools {
namespace xar {
namespace {

// The size of the header (i.e. OFFSET) must be a multiple of 4096 as per the
// contract.
constexpr auto kHeaderSizeBase = 4096;

// Wrapper around std::stoull but require entire string, excluding leading
// whitespace, to be used.
//
// Returns empty string on success and an error message on failure.
std::string parseUll(const std::string& str, unsigned long long* result) {
  errno = 0;
  char* end;
  *result = strtoull(str.c_str(), &end, 10);
  if (end == str.c_str() || end == nullptr || *end != '\0') {
    return "Cannot be parsed as an unsigned integer";
  }
  if (errno != 0) {
    return "Out of range";
  }
  return "";
}

// Parse trampoline names from a string of space separated trampoline names.
// Names are guaranteed to:
// a) Not contain " or '
// b) Not be empty
// c) Be shell-escaped specifically by being surrounded by '' whether or not
//    it's necessary
// d) Separated by exactly one space. The list must also not contain leading
//    or trailing whitespace.
std::optional<XarParserError> parseTrampolineNames(
    const std::string& trampolineNames,
    std::vector<std::string>* ret) {
  if (trampolineNames.size() <= 2) {
    return XarParserError(
        XarParserErrorType::TRAMPOLINE_ERROR,
        "There must be at least one trampoline name. Trampoline names must be"
        "non-empty and surrounded by double quotes");
  }
  if (trampolineNames.front() != '\'' || trampolineNames.back() != '\'') {
    return XarParserError(
        XarParserErrorType::TRAMPOLINE_ERROR,
        "Expected first and last characters to be single quotes that wrap "
        "trampoline names");
  }
  // We have to be careful here to first trim the first and last ' before
  // splitting. Otherwise a ' ' trampoline name might not be handled properly.
  // e.g. consider "' ' 'tramp'"
  *ret = split("' '", trampolineNames.substr(1, trampolineNames.size() - 2));
  bool foundRequiredTrampoline = false;
  for (const auto& trampoline : *ret) {
    if (trampoline.find('\'') != std::string::npos ||
        trampoline.find('"') != std::string::npos) {
      return XarParserError(
          XarParserErrorType::TRAMPOLINE_ERROR,
          "Single or double quotes are not allowed in trampoline names. Maybe "
          "there is more than one space between names?");
    }
    if (trampoline == kGuaranteedTrampolineName) {
      foundRequiredTrampoline = true;
    }
  }
  if (!foundRequiredTrampoline) {
    return XarParserError(
        XarParserErrorType::TRAMPOLINE_ERROR,
        "Missing required trampoline name: " +
            std::string(kGuaranteedTrampolineName));
  }
  return {};
}

} // namespace

namespace detail {

std::optional<XarParserError> parseLine(
    const std::string& line,
    XarHeader* xarHeader,
    std::set<std::string>* foundNames) {
  // Split line into up to 2 parts
  auto nameValue = tools::xar::split(/* delim */ '=', line, /* nsplits */ 1);
  if (nameValue.size() != 2) {
    return XarParserError(XarParserErrorType::MALFORMED_LINE, line);
  }
  const std::string name = std::move(nameValue[0]);
  const std::string wrappedValue = std::move(nameValue[1]);

  if (name.empty() || wrappedValue.size() < 2 || wrappedValue.front() != '"' ||
      wrappedValue.back() != '"') {
    return XarParserError(XarParserErrorType::MALFORMED_LINE, line);
  }
  // Skip quotes around value
  const std::string value = wrappedValue.substr(1, wrappedValue.size() - 2);
  // Check value does not contain '"'
  if (value.find('"') != std::string::npos) {
    return XarParserError(XarParserErrorType::MALFORMED_LINE, line);
  }
  if (foundNames->find(name) != foundNames->end()) {
    // Variable already set. Though we might be able to ignore this, this is
    // probably a bug.
    return XarParserError(XarParserErrorType::DUPLICATE_PARAMETER, name);
  }
  foundNames->emplace(name);

  // Set field in header that corresponds to name
  if (name == kOffsetName) {
    if (auto maybeErrorMsg = parseUll(value, &xarHeader->offset);
        !maybeErrorMsg.empty()) {
      return XarParserError(XarParserErrorType::INVALID_OFFSET, maybeErrorMsg);
    }
    // Verify offset is a strictly positive multiple of kHeaderSizeBase
    if (xarHeader->offset % kHeaderSizeBase != 0 || xarHeader->offset == 0) {
      return XarParserError(
          XarParserErrorType::INVALID_OFFSET,
          std::to_string(xarHeader->offset) +
              " is not a positive multiple of " +
              std::to_string(kHeaderSizeBase));
    }
  } else if (name == kVersion) {
    xarHeader->version = value;
  } else if (name == kUuidName) {
    xarHeader->uuid = value;
  } else if (name == kXarexecTarget) {
    xarHeader->xarexecTarget = value;
  } else if (name == kXarexecTrampolineNames) {
    if (auto maybeError =
            parseTrampolineNames(value, &xarHeader->xarexecTrampolineNames)) {
      return maybeError;
    }
  } else {
    // Unknown parameter or offset (which has already been parsed). Ignore.
  }
  return {};
}

} // namespace detail

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
