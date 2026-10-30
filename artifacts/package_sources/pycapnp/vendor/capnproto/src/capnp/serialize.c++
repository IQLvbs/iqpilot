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

#include "serialize.h"
#include "layout.h"
#include <kj/debug.h>

namespace capnp {

FlatArrayMessageReader::FlatArrayMessageReader(
    kj::ArrayPtr<const word> array, ReaderOptions options)
    : MessageReader(options), end(array.end()) {
  if (array.size() < 1) {
    // Assume empty message.
    return;
  }

  const _::WireValue<uint32_t>* table =
      reinterpret_cast<const _::WireValue<uint32_t>*>(array.begin());

  uint segmentCount = table[0].get() + 1;
  size_t offset = segmentCount / 2u + 1u;

  KJ_REQUIRE(segmentCount != 0, "Message segment count too large, caused overflow.") {
    return;
  }

  KJ_REQUIRE(array.size() >= offset, "Message ends prematurely in segment table.") {
    return;
  }

  {
    uint segmentSize = table[1].get();

    KJ_REQUIRE(array.size() >= offset + segmentSize,
               "Message ends prematurely in first segment.") {
      return;
    }

    segment0 = array.slice(offset, offset + segmentSize);
    offset += segmentSize;
  }

  if (segmentCount > 1) {
    moreSegments = kj::heapArray<kj::ArrayPtr<const word>>(segmentCount - 1);

    for (uint i = 1; i < segmentCount; i++) {
      uint segmentSize = table[i + 1].get();

      KJ_REQUIRE(array.size() >= offset + segmentSize, "Message ends prematurely.") {
        moreSegments = nullptr;
        return;
      }

      moreSegments[i - 1] = array.slice(offset, offset + segmentSize);
      offset += segmentSize;
    }
  }

  end = array.begin() + offset;
}

kj::ArrayPtr<const word> FlatArrayMessageReader::getSegment(uint id) {
  if (id == 0) {
    return segment0;
  } else if (id <= moreSegments.size()) {
    return moreSegments[id - 1];
  } else {
    return nullptr;
  }
}

kj::Array<word> messageToFlatArray(kj::ArrayPtr<const kj::ArrayPtr<const word>> segments) {
  kj::Array<word> result = kj::heapArray<word>(computeSerializedSizeInWords(segments));

  _::WireValue<uint32_t>* table =
      reinterpret_cast<_::WireValue<uint32_t>*>(result.begin());

  // We write the segment count - 1 because this makes the first word zero for single-segment
  // messages, improving compression.  We don't bother doing this with segment sizes because
  // one-word segments are rare anyway.
  table[0].set(segments.size() - 1);

  for (uint i = 0; i < segments.size(); i++) {
    table[i + 1].set(segments[i].size());
  }

  if (segments.size() % 2 == 0) {
    // Set padding byte.
    table[segments.size() + 1].set(0);
  }

  word* dst = result.begin() + segments.size() / 2 + 1;

  for (auto& segment: segments) {
    memcpy(dst, segment.begin(), segment.size() * sizeof(word));
    dst += segment.size();
  }

  KJ_DASSERT(dst == result.end(), "Buffer overrun/underrun bug in code above.");

  return kj::mv(result);
}

size_t computeSerializedSizeInWords(kj::ArrayPtr<const kj::ArrayPtr<const word>> segments) {
  KJ_REQUIRE(segments.size() > 0, "Tried to serialize uninitialized message.");

  size_t totalSize = segments.size() / 2 + 1;

  for (auto& segment: segments) {
    totalSize += segment.size();
  }

  return totalSize;
}

}  // namespace capnp
