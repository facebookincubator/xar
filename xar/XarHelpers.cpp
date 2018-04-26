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
