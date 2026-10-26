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

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif


#include "io.h"
#include "debug.h"
#include "miniposix.h"
#include <algorithm>
#include <errno.h>
#include "vector.h"
#include <limits.h>

#include <sys/uio.h>

namespace kj {

OutputStream::~OutputStream() noexcept(false) {}

void OutputStream::write(ArrayPtr<const ArrayPtr<const byte>> pieces) {
  for (auto piece: pieces) {
    write(piece.begin(), piece.size());
  }
}

AutoCloseFd::~AutoCloseFd() noexcept(false) {
  if (fd >= 0) {
    // Don't use SYSCALL() here because close() should not be repeated on EINTR.
    if (miniposix::close(fd) < 0) {
      KJ_FAIL_SYSCALL("close", errno, fd) {
        // This ensures we don't throw an exception if unwinding.
        break;
      }
    }
  }
}

FdOutputStream::~FdOutputStream() noexcept(false) {}

#if __APPLE__
// macOS cannot handle writes of more than INT_MAX, so we clamp
// writes to this size. We use 1GB rather than INT_MAX since INT_MAX is 2GB minus 1 byte. Being
// off by one from a big round number feels rude (alignment issues may harm performance), and 1GB
// should be plenty in any case.
static constexpr size_t WRITE_CLAMP_SIZE = 1u << 30;
#endif

void FdOutputStream::write(const void* buffer, size_t size) {
  const char* pos = reinterpret_cast<const char*>(buffer);

  while (size > 0) {
    miniposix::ssize_t n;
#if __APPLE__
    // macOS fails if given more than INT_MAX bytes
    // in a single write operation. We can just clamp the size since the loop will then handle
    // writing the rest. I don't know why these platforms don't just do this themselves.
    KJ_SYSCALL(n = miniposix::write(fd, pos, kj::min(size, WRITE_CLAMP_SIZE)), fd);
#else
    KJ_SYSCALL(n = miniposix::write(fd, pos, size), fd);
#endif
    KJ_ASSERT(n > 0, "write() returned zero.");
    pos += n;
    size -= n;
  }
}

void FdOutputStream::write(ArrayPtr<const ArrayPtr<const byte>> pieces) {
  const size_t iovmax = miniposix::iovMax();
  while (pieces.size() > iovmax) {
    write(pieces.slice(0, iovmax));
    pieces = pieces.slice(iovmax, pieces.size());
  }

  KJ_STACK_ARRAY(struct iovec, iov, pieces.size(), 16, 128);

  for (uint i = 0; i < pieces.size(); i++) {
    // writev() interface is not const-correct.  :(
    iov[i].iov_base = const_cast<byte*>(pieces[i].begin());
    iov[i].iov_len = pieces[i].size();
  }

  struct iovec* current = iov.begin();

  // Advance past any leading empty buffers so that a write full of only empty buffers does not
  // cause a syscall at all.
  while (current < iov.end() && current->iov_len == 0) {
    ++current;
  }

  while (current < iov.end()) {
    size_t iovCount = iov.end() - current;

#if __APPLE__
    // MacOS will fail if you give it more than INT_MAX bytes to write at once. We can solve this
    // by carefully truncating the list to a lesser number. Why the OS doesn't just return a short
    // write itself, I don't know.
    size_t totalSize = 0;
    struct iovec* editedPiece = nullptr;
    size_t editedPieceOriginalLen = 0;
    for (auto i: kj::zeroTo(iovCount)) {
      auto& piece = *(current + i);
      totalSize += piece.iov_len;
      if (totalSize >= WRITE_CLAMP_SIZE) {
        // Truncate the list after this piece.
        iovCount = i + 1;

        if (totalSize > WRITE_CLAMP_SIZE) {
          // We also have to truncate this piece. Patch it in-place and plan to fix it later.
          editedPiece = &piece;
          editedPieceOriginalLen = piece.iov_len;
          size_t overage = totalSize - WRITE_CLAMP_SIZE;
          piece.iov_len -= overage;
        }

        break;
      }
    }
#endif

    // Issue the write.
    ssize_t n = 0;
    KJ_SYSCALL(n = ::writev(fd, current, iovCount), fd);
    KJ_ASSERT(n > 0, "writev() returned zero.");

#if __APPLE__
    // If we patched the list above, unpatch now.
    if (editedPiece != nullptr) {
      editedPiece->iov_len = editedPieceOriginalLen;
    }
#endif

    // Advance past all buffers that were fully-written.
    while (current < iov.end() && static_cast<size_t>(n) >= current->iov_len) {
      n -= current->iov_len;
      ++current;
    }

    // If we only partially-wrote one of the buffers, adjust the pointer and size to include only
    // the unwritten part.
    if (n > 0) {
      current->iov_base = reinterpret_cast<byte*>(current->iov_base) + n;
      current->iov_len -= n;
    }
  }
}

// =======================================================================================


}  // namespace kj
