// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree

#include "FileUtil.h"

namespace tools {
namespace xar {

int openNoInt(const char* name, int flags, mode_t mode) {
  auto openWrapper = [&] { return open(name, flags, mode); };
  return int(detail::wrapNoInt(openWrapper));
}

static int filterCloseReturn(int r) {
  if (r == -1 && errno == EINTR) {
    return 0;
  }
  return r;
}

int closeNoInt(int fd) {
  return filterCloseReturn(close(fd));
}

ssize_t readNoInt(int fd, void* buf, size_t count) {
  return detail::wrapNoInt(read, fd, buf, count);
}

ssize_t readFull(int fd, void* buf, size_t count) {
  return detail::wrapFull(read, fd, buf, count);
}

ssize_t writeNoInt(int fd, const void* buf, size_t count) {
  return detail::wrapNoInt(write, fd, buf, count);
}

ssize_t writeFull(int fd, const void* buf, size_t count) {
  return detail::wrapFull(write, fd, const_cast<void*>(buf), count);
}

} // namespace xar
} // namespace tools
