// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree

#pragma once

#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <cerrno>
#include <cstddef>
#include <type_traits>

namespace tools {
namespace xar {

namespace detail {

// Wrap call to f(args) in loop to retry on EINTR
template <class F, class... Args>
ssize_t wrapNoInt(F f, Args... args) {
  ssize_t r;
  do {
    r = f(args...);
  } while (r == -1 && errno == EINTR);
  return r;
}

template <class F>
ssize_t wrapFull(F f, int fd, void* buf, size_t count) {
  char* b = static_cast<char*>(buf);
  ssize_t totalBytes = 0;
  ssize_t r;
  do {
    r = f(fd, b, count);
    if (r == -1) {
      if (errno == EINTR) {
        continue;
      }
      return r;
    }

    totalBytes += r;
    b += r;
    count -= r;
  } while (r != 0 && count); // 0 means EOF

  return totalBytes;
}

} // namespace detail

/**
 * Convenience wrappers around some commonly used system calls.  The *NoInt
 * wrappers retry on EINTR.  The *Full wrappers retry on EINTR and also loop
 * until all data is written.  Note that *Full wrappers weaken the thread
 * semantics of underlying system calls.
 */
int openNoInt(const char* name, int flags, mode_t mode = 0666);
int closeNoInt(int fd);

ssize_t readNoInt(int fd, void* buf, size_t count);

/**
 * Wrapper around read() that, in addition to retrying on EINTR, will loop until
 * all data is read.
 *
 * This wrapper is only useful for blocking file descriptors (for non-blocking
 * file descriptors, you have to be prepared to deal with incomplete reads
 * anyway), and only exists because POSIX allows read() to return an incomplete
 * read if interrupted by a signal (instead of returning -1 and setting errno
 * to EINTR).
 *
 * Note that this wrapper weakens the thread safety of read(): the file pointer
 * is shared between threads, but the system call is atomic.  If multiple
 * threads are reading from a file at the same time, you don't know where your
 * data came from in the file, but you do know that the returned bytes were
 * contiguous.  You can no longer make this assumption if using readFull().
 */
[[nodiscard]] ssize_t readFull(int fd, void* buf, size_t count);

ssize_t writeNoInt(int fd, const void* buf, size_t count);

/**
 * Similar to readFull above, wraps write and loop until all data is written.
 *
 * Generally, the write() system call may always write fewer bytes than
 * requested, just like read().  In certain cases (such as when writing to a
 * pipe), POSIX provides stronger guarantees, but not in the general case. For
 * example, Linux (even on a 64-bit platform) won't write more than 2GB in one
 * write() system call.
 *
 * This function returns -1 on error, or the total number of bytes written
 * (which is always the same as the number of requested bytes) on success.
 */
ssize_t writeFull(int fd, const void* buf, size_t count);

} // namespace xar
} // namespace tools
