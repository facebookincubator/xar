// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#include "XarHelpers.h"

namespace tools {
namespace xar {
namespace {
const size_t kDefaultHeaderSize = 4096;
}

std::unordered_map<std::string, std::string> read_xar_header(
    const char* filename) {
  int fd = open(filename, O_RDONLY | O_CLOEXEC);
  if (fd < 0) {
    FATAL << "open " << filename << ": " << strerror(errno);
  }

  std::string buf;
  buf.resize(kDefaultHeaderSize);
  ssize_t res = read(fd, &buf[0], buf.size());
  if (res < 0) {
    FATAL << "read header from: " << filename << ": " << strerror(errno);
  }
  if (res != buf.size()) {
    FATAL << "Short read of header of " << filename;
  }
  res = close(fd);
  if (res < 0) {
    FATAL << "close " << filename << ": " << strerror(errno);
  }

  std::unordered_map<std::string, std::string> ret;
  auto lines = tools::xar::split('\n', buf);
  for (const auto& line : lines) {
    if (line == "#xar_stop") {
      break;
    }
    if (line.empty() || line[0] == '#') {
      continue;
    }

    auto name_value = tools::xar::split('=', line);
    if (name_value.size() != 2) {
      FATAL << "malformed header line: " << line;
    }
    std::string name = name_value[0];
    std::string value = name_value[1];

    if (name.empty() || value.size() < 2 || value.front() != '"' ||
        value.back() != '"') {
      FATAL << "invalid line in xar header: " << line;
    }
    // skip quotes around value
    ret[name] = value.substr(1, value.size() - 2);
  }

  if (ret.find(kOffsetName) == ret.end() ||
      ret[kOffsetName] != std::to_string(kDefaultHeaderSize)) {
    FATAL << "TODO(chip): support headers other than he default";
  }

  if (ret.find(kUuidName) == ret.end()) {
    FATAL << "No UUID in XAR header";
  }

  if (debugging) {
    for (const auto& p : ret) {
      std::cerr << "header " << p.first << "=" << p.second << std::endl;
    }
  }

  return ret;
}

namespace detail {
static std::string buffer;

LogFatal::~LogFatal() {
  // Keep a static forensics variable preserve the error message; this lets
  // us inspect it from the core since stderr is often not saved.
  buffer = ostream.str();
  std::cerr << buffer << std::endl;
  abort();
}

} // namespace detail
} // namespace xar
} // namespace tools
