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

// This header provides a small subset of the POSIX API.

#include <limits.h>
#include <errno.h>

#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>

#include <sys/uio.h>

// To get KJ_BEGIN_HEADER/KJ_END_HEADER
#include "common.h"

KJ_BEGIN_HEADER

namespace kj {
namespace miniposix {

using ::ssize_t;
using ::read;
using ::write;
using ::close;


using ::pipe;
using ::mkdir;


// Apparently, there is a maximum number of iovecs allowed per call.  I don't understand why.
// Most platforms define IOV_MAX but Linux defines only UIO_MAXIOV and others, like Hurd,
// define neither.
//
// On platforms where both IOV_MAX and UIO_MAXIOV are undefined, we poke sysconf(_SC_IOV_MAX),
// then try to fall back to the POSIX-mandated minimum of _XOPEN_IOV_MAX if that fails.
//
// http://pubs.opengroup.org/onlinepubs/9699919799/basedefs/limits.h.html#tag_13_23_03_01
#if defined(IOV_MAX)
// Solaris, MacOS (& all other BSD-variants?) (and others?)
static constexpr inline size_t iovMax() {
  return IOV_MAX;
}
#elif defined(UIO_MAX_IOV)
// Linux
static constexpr inline size_t iovMax() {
  return UIO_MAX_IOV;
}
#else
#error "Please determine the appropriate constant for IOV_MAX on your system."
#endif


}  // namespace miniposix
}  // namespace kj

KJ_END_HEADER
