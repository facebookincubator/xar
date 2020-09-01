// Copyright (c) 2020-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#include <unistd.h>

#include "XarHelpers.h"

namespace {
using std::cerr;
using std::endl;

void usage() {
  cerr << "Usage: unxar [-h] XAR DEST [...]" << endl
       << endl
       << "Unpacks the XAR to the DEST directory. Any extra arguments are "
       << endl
       << "forwarded to unsquashfs." << endl
       << endl
       << "Options: " << endl
       << "     -h: print help message and exit" << endl;
}

char* pop_arg(int& argc, char**& argv) {
  if (argc == 0) {
    FATAL << "Bad argument parsing logic!";
  }
  char* const arg = argv[0];
  ++argv;
  --argc;
  return arg;
}
} // namespace

int main(int argc, char** argv) {
  // Need at least one argument.
  if (argc < 2) {
    usage();
    return 1;
  }
  // Pop the executable name.
  pop_arg(argc, argv);
  // Pop and handle any flags.
  while (argc > 0 && argv[0][0] == '-') {
    const char* const arg = pop_arg(argc, argv);
    if (strcmp(arg, "-h") == 0) {
      // Help.
      usage();
      return 0;
    } else if (strcmp(arg, "--") == 0) {
      // End of flags.
      break;
    } else {
      usage();
      return 1;
    }
  }
  // Pop the xar path and the dest path.
  if (argc < 2) {
    usage();
    return 1;
  }
  char* const xar_path = pop_arg(argc, argv);
  char* const dest_path = pop_arg(argc, argv);
  // Any further arguments get passed as options to unsquashfs.

  // Read the XAR headers.
  auto header = tools::xar::read_xar_header(xar_path);

  // Call unsquashfs to unpack xar_path to dest_path with the correct -offset
  // and any extra flags the user wants. User flags must go before the xar_path.
  char* newArgs[argc + 7];
  newArgs[0] = strdup("unsquashfs");
  newArgs[1] = strdup("-offset");
  newArgs[2] = strdup(header[tools::xar::kOffsetName].c_str());
  newArgs[3] = strdup("-dest");
  newArgs[4] = dest_path;
  for (int i = 0; i < 4; ++i) {
    if (!newArgs[i]) {
      FATAL << "strdup failed, call the cops"
            << ": " << strerror(errno);
    }
  }
  for (int i = 0; i < argc; ++i) {
    newArgs[5 + i] = argv[i];
  }
  newArgs[5 + argc] = xar_path;
  newArgs[6 + argc] = nullptr;

  for (int i = 0; newArgs[i]; ++i) {
    if (tools::xar::debugging) {
      cerr << "  exec arg: " << newArgs[i] << endl;
    }
  }

  if (execvp(newArgs[0], newArgs) != 0) {
    FATAL << "execv: " << strerror(errno) << "cmd: " << newArgs[0];
  }
}
