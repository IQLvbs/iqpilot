// Copyright (c) 2017 Cloudflare, Inc. and contributors
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
// C-style string escaping.

#include "string.h"

KJ_BEGIN_HEADER

namespace kj {

String encodeCEscape(ArrayPtr<const byte> bytes);
String encodeCEscape(ArrayPtr<const char> bytes);

// =======================================================================================
// inline implementation details

namespace _ {  // private

String encodeCEscapeImpl(ArrayPtr<const byte> bytes, bool isBinary);

}  // namespace _ (private)

inline String encodeCEscape(ArrayPtr<const char> text) {
  return _::encodeCEscapeImpl(text.asBytes(), false);
}

inline String encodeCEscape(ArrayPtr<const byte> bytes) {
  return _::encodeCEscapeImpl(bytes, true);
}


// If you pass a string literal to a function taking ArrayPtr<const char>, it'll include the NUL
// terminator. These overloads avoid including it.

template <size_t s>
inline String encodeCEscape(const char (&text)[s]) {
  return encodeCEscape(arrayPtr(text, s - 1));
}

#if __cpp_char8_t
template <size_t s>
inline String encodeCEscape(const char8_t (&text)[s]) {
  return encodeCEscape(arrayPtr(reinterpret_cast<const char*>(text), s - 1));
}
#endif

} // namespace kj

KJ_END_HEADER
