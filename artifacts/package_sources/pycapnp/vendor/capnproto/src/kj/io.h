// Copyright (c) 2013-2014 Sandstorm Development Group, Inc. and contributors
// Licensed under the MIT License:
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.

#pragma once

#include <stddef.h>
#include "common.h"
#include "array.h"
#include "exception.h"
#include <stdint.h>

KJ_BEGIN_HEADER

namespace kj {

// =======================================================================================
// Abstract interfaces

class OutputStream {
public:
  virtual ~OutputStream() noexcept(false);

  virtual void write(const void* buffer, size_t size) = 0;
  // Always writes the full size.  Throws exception on error.

  virtual void write(ArrayPtr<const ArrayPtr<const byte>> pieces);
  // Equivalent to write()ing each byte array in sequence, which is what the default implementation
  // does.  Override if you can do something better, e.g. use writev() to do the write in a single
  // syscall.
};

// =======================================================================================
// File descriptor I/O

class AutoCloseFd {
  // A wrapper around a file descriptor which automatically closes the descriptor when destroyed.
  // The wrapper supports move construction for transferring ownership of the descriptor.  If
  // close() returns an error, the destructor throws an exception, UNLESS the destructor is being
  // called during unwind from another exception, in which case the close error is ignored.
  //
  // If your code is not exception-safe, you should not use AutoCloseFd.  In this case you will
  // have to call close() yourself and handle errors appropriately.

public:
  inline AutoCloseFd(): fd(-1) {}
  inline AutoCloseFd(decltype(nullptr)): fd(-1) {}
  inline explicit AutoCloseFd(int fd): fd(fd) {}
  inline AutoCloseFd(AutoCloseFd&& other) noexcept: fd(other.fd) { other.fd = -1; }
  KJ_DISALLOW_COPY(AutoCloseFd);
  ~AutoCloseFd() noexcept(false);

  inline AutoCloseFd& operator=(AutoCloseFd&& other) {
    AutoCloseFd old(kj::mv(*this));
    fd = other.fd;
    other.fd = -1;
    return *this;
  }

  inline AutoCloseFd& operator=(decltype(nullptr)) {
    AutoCloseFd old(kj::mv(*this));
    return *this;
  }

  inline operator int() const { return fd; }
  inline int get() const { return fd; }

  operator bool() const = delete;
  // Deleting this operator prevents accidental use in boolean contexts, which
  // the int conversion operator above would otherwise allow.

  inline bool operator==(decltype(nullptr)) { return fd < 0; }
  inline bool operator!=(decltype(nullptr)) { return fd >= 0; }

  inline int release() {
    // Release ownership of an FD. Not recommended.
    int result = fd;
    fd = -1;
    return result;
  }

private:
  int fd;
};

inline auto KJ_STRINGIFY(const AutoCloseFd& fd)
    -> decltype(kj::toCharSequence(implicitCast<int>(fd))) {
  return kj::toCharSequence(implicitCast<int>(fd));
}

class FdOutputStream: public OutputStream {
  // An OutputStream wrapping a file descriptor.

public:
  explicit FdOutputStream(int fd): fd(fd) {}
  explicit FdOutputStream(AutoCloseFd fd): fd(fd), autoclose(mv(fd)) {}
  KJ_DISALLOW_COPY_AND_MOVE(FdOutputStream);
  ~FdOutputStream() noexcept(false);

  void write(const void* buffer, size_t size) override;
  void write(ArrayPtr<const ArrayPtr<const byte>> pieces) override;

  inline int getFd() const { return fd; }

private:
  int fd;
  AutoCloseFd autoclose;
};

}  // namespace kj

KJ_END_HEADER
