// Copyright (c) 2018-present, Facebook, Inc.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree

#include "FileUtil.h"

#include <deque>
#if defined(__linux__)
#include <dlfcn.h>
#endif

#include <gmock/gmock.h>
#include <gtest/gtest.h>

namespace tools {
namespace xar {

namespace {

template <const int MAX_LEN, std::size_t N>
constexpr auto& STR_LEN_EQ(char const (&s)[N]) {
  static_assert(N - 1 == MAX_LEN, "String is not the expected size");
  return s;
}

class Reader {
 public:
  Reader(off_t offset, const std::string& data, std::deque<ssize_t> spec);

  // write-like
  ssize_t operator()(int fd, void* buf, size_t count);

 private:
  ssize_t nextSize();

  off_t offset_;
  std::string data_;
  std::deque<ssize_t> spec_;
};

Reader::Reader(off_t offset, const std::string& data, std::deque<ssize_t> spec)
    : offset_(offset), data_(data), spec_(std::move(spec)) {}

ssize_t Reader::nextSize() {
  if (spec_.empty()) {
    throw std::runtime_error("spec empty");
  }
  ssize_t n = spec_.front();
  spec_.pop_front();
  if (n <= 0) {
    if (n == -1) {
      errno = EIO;
    }
    spec_.clear(); // so we fail if called again
  } else {
    offset_ += n;
  }
  return n;
}

ssize_t Reader::operator()(int /* fd */, void* buf, size_t count) {
  ssize_t n = nextSize();
  if (n <= 0) {
    return n;
  }
  if (size_t(n) > count) {
    throw std::runtime_error("requested count too small");
  }
  memcpy(buf, data_.data(), n);
  data_.erase(0, n);
  return n;
}

} // namespace

class FileUtilTest : public ::testing::Test {
 protected:
  FileUtilTest();

  Reader reader(std::deque<ssize_t> spec);

  std::string in_;
  std::vector<std::pair<size_t, Reader>> readers_;
};

FileUtilTest::FileUtilTest() {
  constexpr char testIn[] =
      "1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
  STR_LEN_EQ<62>(testIn); // Check string size is what we expect
  in_ = testIn;

  readers_.emplace_back(0, reader({0}));
  readers_.emplace_back(62, reader({62}));
  readers_.emplace_back(62, reader({62, -1})); // error after end (not called)
  readers_.emplace_back(61, reader({61, 0}));
  readers_.emplace_back(-1, reader({61, -1})); // error before end
  readers_.emplace_back(62, reader({31, 31}));
  readers_.emplace_back(62, reader({1, 10, 20, 10, 1, 20}));
  readers_.emplace_back(61, reader({1, 10, 20, 10, 20, 0}));
  readers_.emplace_back(41, reader({1, 10, 20, 10, 0}));
  readers_.emplace_back(-1, reader({1, 10, 20, 10, 20, -1}));
}

Reader FileUtilTest::reader(std::deque<ssize_t> spec) {
  return Reader(42, in_, std::move(spec));
}

TEST_F(FileUtilTest, read) {
  for (auto& p : readers_) {
    std::string out(in_.size(), '\0');
    EXPECT_EQ(p.first, detail::wrapFull(p.second, 0, &out[0], out.size()));
    if (p.first != (decltype(p.first))(-1)) {
      EXPECT_EQ(in_.substr(0, p.first), out.substr(0, p.first));
    }
  }
}

class ReadFileFd : public ::testing::Test {
 protected:
  void SetUp() override {
    char filename[] = "/tmp/fileutiltest_XXXXXX";
    int writeFd = ::mkstemp(filename);
    _filename = filename;

    ASSERT_FALSE(writeFd < 0);
    ASSERT_EQ(writeFull(writeFd, "bar", 3), 3);

    closeNoInt(writeFd);

    // open file for read only
    _fd = openNoInt(filename, O_RDONLY);
    ::unlink(filename);
    ASSERT_NE(::lseek(_fd, 0, SEEK_SET), -1);
  }

  void TearDown() override {
    closeNoInt(_fd);
  }

  std::string _filename;
  int _fd;
};

TEST_F(ReadFileFd, ReadZeroBytes) {
  std::vector<char> buf(3, 0);
  int bytes = readFull(_fd, buf.data(), 0);
  EXPECT_EQ(bytes, 0);
}

TEST_F(ReadFileFd, ReadPartial) {
  std::vector<char> buf(3, 0);
  EXPECT_EQ(readFull(_fd, buf.data(), 2), 2);
  buf.resize(2);
  EXPECT_EQ(std::vector<char>({'b', 'a'}), buf);
}

TEST_F(ReadFileFd, ReadFull) {
  std::vector<char> buf(3, 0);
  ASSERT_EQ(readFull(_fd, buf.data(), 3), 3);
  EXPECT_EQ(std::vector<char>({'b', 'a', 'r'}), buf);
}

TEST_F(ReadFileFd, WriteOnlyFd) {
  int fd = openNoInt(_filename.c_str(), O_WRONLY);
  std::vector<char> buf(3, 0);
  EXPECT_EQ(readFull(fd, buf.data(), 3), -1);
  closeNoInt(fd);
}

TEST_F(ReadFileFd, InvalidFd) {
  closeNoInt(_fd);
  std::vector<char> buf(3, 0);
  EXPECT_EQ(readFull(_fd, buf.data(), 3), -1);
}

} // namespace xar
} // namespace tools
