// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#include <algorithm>
#include <iostream>

#include "XarParser.h"

void help(const char* progName) {
  std::cout << "usage: " << progName << " [OPTIONS] PATH_TO_XAR\n\n"
            << "Validate XAR header and squashfs magic at offset and print\n"
            << "parsed header as JSON. Output will be in one line, with no\n"
            << "unnecessary whitespace. Keys will be as they appear in the\n"
            << "XAR header. Values are serialized according to their type\n"
            << "(e.g. strings are wrapped with double quotes, integers are\n"
            << "not).\n\n"
            << "Options:\n"
            << "    -h, --help  Display this message\n\n";
}

void usage(const char* progName) {
  std::cerr << "invalid usage\n(use " << progName << " --help to get help)\n";
}

int main(int argc, char* argv[]) {
  if (argc > 1 &&
      (!std::strcmp(argv[1], "--help") || !std::strcmp(argv[1], "-h"))) {
    help(argv[0]);
    return 0;
  }

  if (argc != 2) {
    usage(argv[0]);
    return -1;
  }

  const auto xarPath = argv[1];
  const auto maybeXarHeader = tools::xar::parseXarHeader(xarPath);
  if (maybeXarHeader.hasError()) {
    std::cerr << "Error parsing XAR header: "
              << maybeXarHeader.error().getErrorMessage() << "\n";
    return -1;
  }
  const auto& header = maybeXarHeader.value();
  std::cout << tools::xar::serializeHeaderAsJSON(header) << "\n";
  return 0;
}
