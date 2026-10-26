// Copyright (c) 2014 Google Inc. (contributed by Remy Blank <rblank@google.com>)
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


#include "time.h"
#include "debug.h"

#include <time.h>

namespace kj {

const Clock& nullClock() {
  class NullClock final: public Clock {
  public:
    Date now() const override { return UNIX_EPOCH; }
  };
  static KJ_CONSTEXPR(const) NullClock NULL_CLOCK = NullClock();
  return NULL_CLOCK;
}


namespace {

class PosixMonotonicClock: public MonotonicClock {
public:
  constexpr PosixMonotonicClock(clockid_t clockId): clockId(clockId) {}

  TimePoint now() const override {
    struct timespec ts;
    KJ_SYSCALL(clock_gettime(clockId, &ts));
    return kj::origin<TimePoint>() + ts.tv_sec * kj::SECONDS + ts.tv_nsec * kj::NANOSECONDS;
  }

private:
  clockid_t clockId;
};

}  // namespace

// FreeBSD has "_PRECISE", but Linux just defaults to precise.
#ifndef CLOCK_MONOTONIC_PRECISE
#define CLOCK_MONOTONIC_PRECISE CLOCK_MONOTONIC
#endif

const MonotonicClock& systemPreciseMonotonicClock() {
  static constexpr PosixMonotonicClock clock(CLOCK_MONOTONIC_PRECISE);
  return clock;
}


CappedArray<char, _::TIME_STR_LEN> KJ_STRINGIFY(TimePoint t) {
  return kj::toCharSequence(t - kj::origin<TimePoint>());
}
CappedArray<char, _::TIME_STR_LEN> KJ_STRINGIFY(Date d) {
  return kj::toCharSequence(d - UNIX_EPOCH);
}
CappedArray<char, _::TIME_STR_LEN> KJ_STRINGIFY(Duration d) {
  bool negative = d < 0 * kj::SECONDS;
  uint64_t ns = d / kj::NANOSECONDS;
  if (negative) {
    ns = -ns;
  }

  auto digits = kj::toCharSequence(ns);
  ArrayPtr<char> arr = digits;

  size_t point;
  kj::StringPtr suffix;
  kj::Duration unit;
  if (digits.size() > 9) {
    point = arr.size() - 9;
    suffix = "s";
    unit = kj::SECONDS;
  } else if (digits.size() > 6) {
    point = arr.size() - 6;
    suffix = "ms";
    unit = kj::MILLISECONDS;
  } else if (digits.size() > 3) {
    point = arr.size() - 3;
    suffix = "μs";
    unit = kj::MICROSECONDS;
  } else {
    point = arr.size();
    suffix = "ns";
    unit = kj::NANOSECONDS;
  }

  CappedArray<char, _::TIME_STR_LEN> result;
  char* begin = result.begin();
  char* end;
  if (negative) {
    *begin++ = '-';
  }
  if (d % unit == 0 * kj::NANOSECONDS) {
    end = _::fillLimited(begin, result.end(), arr.slice(0, point), suffix);
  } else {
    while (arr.back() == '0') {
      arr = arr.slice(0, arr.size() - 1);
    }
    KJ_DASSERT(arr.size() > point);
    end = _::fillLimited(begin, result.end(), arr.slice(0, point), "."_kj,
        arr.slice(point, arr.size()), suffix);
  }
  result.setSize(end - result.begin());
  return result;
}

}  // namespace kj
