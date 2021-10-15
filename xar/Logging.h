// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#include <cstring>
#include <sstream>

// Inspired by glog's CHECK/PCHECK, these macros don't rely on glog
// itself, which we intentionally avoid due to issues using it in a
// setuid context.
#define XAR_CHECK_SIMPLE(test) \
  do {                         \
    if (!(test)) {             \
      try {                    \
        XAR_FATAL << #test;    \
      } catch (...) {          \
      }                        \
      abort();                 \
    }                          \
  } while (0)

#define XAR_PCHECK_SIMPLE(test)                        \
  do {                                                 \
    if (!(test)) {                                     \
      try {                                            \
        XAR_FATAL << #test << ": " << strerror(errno); \
      } catch (...) {                                  \
      }                                                \
      abort();                                         \
    }                                                  \
  } while (0)

#define XAR_FATAL                            \
  (::tools::xar::detail::LogFatal().stream() \
   << "FATAL " << __FILE__ << ":" << __LINE__ << ": ")

namespace tools {
namespace xar {

namespace detail {

// A simple, poor man's version of Google logging. Use the XAR_FATAL
// macro and not this class directly.
class LogFatal {
 public:
  // The attributes here are to prevent optimizations that may
  // obfuscate our stack trace.
  ~LogFatal() __attribute__((__noreturn__, __noinline__));
  std::ostream& stream() {
    return ostream;
  }

 private:
  std::stringstream ostream;
};

} // namespace detail

} // namespace xar
} // namespace tools
