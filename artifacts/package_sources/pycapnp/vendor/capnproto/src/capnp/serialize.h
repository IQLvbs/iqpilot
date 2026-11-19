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

// This file implements a simple serialization format for Cap'n Proto messages.  The format
// is as follows:
//
// * 32-bit little-endian segment count (4 bytes).
// * 32-bit little-endian size of each segment (4*(segment count) bytes).
// * Padding so that subsequent data is 64-bit-aligned (0 or 4 bytes).  (I.e., if there are an even
//     number of segments, there are 4 bytes of zeros here, otherwise there is no padding.)
// * Data from each segment, in order (8*sum(segment sizes) bytes)
//
// This format has some important properties:
// - It is self-delimiting, so multiple messages may be written to a stream without any external
//   delimiter.
// - The total size and position of each segment can be determined by reading only the first part
//   of the message, allowing lazy and random-access reading of the segment data.
// - A message is always at least 8 bytes.
// - A single-segment message can be read entirely in two system calls with no buffering.
// - A multi-segment message can be read entirely in three system calls with no buffering.
// - The format is appropriate for mmap()ing since all data is aligned.

#pragma once

#include "message.h"

CAPNP_BEGIN_HEADER

namespace capnp {

class FlatArrayMessageReader: public MessageReader {
  // Parses a message from a flat array.  Note that it makes sense to use this together with mmap()
  // for extremely fast parsing.

public:
  FlatArrayMessageReader(kj::ArrayPtr<const word> array, ReaderOptions options = ReaderOptions());
  // The array must remain valid until the MessageReader is destroyed.

  kj::ArrayPtr<const word> getSegment(uint id) override;

  const word* getEnd() const { return end; }
  // Get a pointer just past the end of the message as determined by reading the message header.
  // This could actually be before the end of the input array.  This pointer is useful e.g. if
  // you know that the input array has extra stuff appended after the message and you want to
  // get at it.

private:
  // Optimize for single-segment case.
  kj::ArrayPtr<const word> segment0;
  kj::Array<kj::ArrayPtr<const word>> moreSegments;
  const word* end;
};

kj::Array<word> messageToFlatArray(MessageBuilder& builder);
// Constructs a flat array containing the entire content of the given message.
//
// To output the message as bytes, use `.asBytes()` on the returned word array. Keep in mind that
// `asBytes()` returns an ArrayPtr, so you have to save the Array as well to prevent it from being
// deleted. For example:
//
//     kj::Array<capnp::word> words = messageToFlatArray(myMessage);
//     kj::ArrayPtr<kj::byte> bytes = words.asBytes();
//     write(fd, bytes.begin(), bytes.size());

kj::Array<word> messageToFlatArray(kj::ArrayPtr<const kj::ArrayPtr<const word>> segments);
// Version of messageToFlatArray that takes a raw segment array.

size_t computeSerializedSizeInWords(kj::ArrayPtr<const kj::ArrayPtr<const word>> segments);
// Version of computeSerializedSizeInWords that takes a raw segment array.

inline kj::Array<word> messageToFlatArray(MessageBuilder& builder) {
  return messageToFlatArray(builder.getSegmentsForOutput());
}

}  // namespace capnp

CAPNP_END_HEADER
