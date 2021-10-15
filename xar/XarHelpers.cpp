// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#include "XarHelpers.h"
#include "Logging.h"

namespace tools {
namespace xar {
namespace {
const size_t kDefaultHeaderSize = 4096;

std::optional<std::string> read_file_prefix(
    const char* filename,
    size_t max_bytes) {
  int fd = open(filename, O_RDONLY | O_CLOEXEC);
  if (fd < 0) {
    return std::nullopt;
  }

  std::string buf;
  buf.resize(max_bytes);
  ssize_t res = read(fd, &buf[0], buf.size());
  if (res < 0) {
    return std::nullopt;
  }
  buf.resize(res);
  res = close(fd);
  if (res < 0) {
    return std::nullopt;
  }

  return buf;
}

} // namespace

std::unordered_map<std::string, std::string> read_xar_header(
    const char* filename) {
  const auto maybe_header = read_file_prefix(filename, kDefaultHeaderSize);
  if (!maybe_header) {
    XAR_FATAL << "Unable to open or read XAR header from " << filename;
  }
  const auto header = *maybe_header;
  if (header.size() != kDefaultHeaderSize) {
    XAR_FATAL << "Short read of header of " << filename << ", " << header.size()
              << " vs expected " << kDefaultHeaderSize;
  }

  std::unordered_map<std::string, std::string> ret;
  auto lines = tools::xar::split('\n', header);
  for (const auto& line : lines) {
    if (line == "#xar_stop") {
      break;
    }
    if (line.empty() || line[0] == '#') {
      continue;
    }

    auto name_value = tools::xar::split('=', line, 1);
    if (name_value.size() != 2) {
      XAR_FATAL << "malformed header line: " << line;
    }
    std::string name = name_value[0];
    std::string value = name_value[1];

    if (name.empty() || value.size() < 2 || value.front() != '"' ||
        value.back() != '"') {
      XAR_FATAL << "invalid line in xar header: " << line;
    }
    // skip quotes around value
    ret[name] = value.substr(1, value.size() - 2);
  }

  if (ret.find(kOffsetName) == ret.end() ||
      ret[kOffsetName] != std::to_string(kDefaultHeaderSize)) {
    XAR_FATAL << "TODO(chip): support headers other than he default";
  }

  if (ret.find(kUuidName) == ret.end()) {
    XAR_FATAL << "No UUID in XAR header";
  }

  if (debugging) {
    for (const auto& p : ret) {
      std::cerr << "header " << p.first << "=" << p.second << std::endl;
    }
  }

  return ret;
}

std::optional<ino_t> read_sysfs_cgroup_inode(const char* filename) {
  const auto maybe_contents = read_file_prefix(filename, 4096);
  if (!maybe_contents) {
    return std::nullopt;
  }
  const auto contents = *maybe_contents;
  if (contents.size() == 4096) {
    return std::nullopt;
  }

  // File contents are a colon-separated triplet.  We want the last
  // field, and to toss out the trailing newline.
  auto components = tools::xar::split(':', contents);
  if (components.size() < 3) {
    return std::nullopt;
  }
  auto newline_pos = components[2].find('\n');
  if (newline_pos != std::string::npos) {
    components[2].erase(newline_pos);
  }

  // /sys/fs/cgroup is the typical mount point for the cgroup2
  // filesystem, but it is not guaranteed.  In some FB environments
  // we've historically used /cgroup2 instead.
  for (auto& candidate : {"/sys/fs/cgroup", "/cgroup2"}) {
    auto path = std::string(candidate) + "/" + components[2];
    struct stat st;
    if (stat(path.c_str(), &st) == 0) {
      return st.st_ino;
    }
  }

  return std::nullopt;
}

std::string serializeHeaderAsJSON(const XarHeader& header) noexcept {
  std::string ret = "{";
  for (const auto& [name, value] :
       std::initializer_list<std::pair<std::string, std::string>>{
           {kOffsetName, std::to_string(header.offset)},
           {kUuidName, "\"" + header.uuid + "\""},
           {kVersion, "\"" + header.version + "\""},
           {kXarexecTarget, "\"" + header.xarexecTarget + "\""},
           {kXarexecTrampolineNames,
            "[\"" + join("\",\"", header.xarexecTrampolineNames) + "\"]"}}) {
    if (ret.size() > 1) {
      ret += ",";
    }
    ret += "\"";
    ret += name;
    ret += "\":";
    ret += value;
  }
  ret += "}";
  return ret;
}

} // namespace xar
} // namespace tools
