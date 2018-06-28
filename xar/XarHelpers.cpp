// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#include "XarHelpers.h"

namespace tools {
namespace xar {
namespace detail {

LogFatal::~LogFatal() {
  // Keep a local forensics variable with the error message; this lets
  // us inspect it from the core since stderr is often not saved.
  // Trick borrowed from folly to prevent our buffer from disappearing.
  std::string buffer(ostream.str());
  asm volatile("" ::"m"(buffer) : "memory");

  std::cerr << buffer << std::endl;
  abort();
}

} // namespace detail
} // namespace xar
} // namespace tools
