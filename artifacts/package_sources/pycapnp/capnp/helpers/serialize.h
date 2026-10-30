// Copyright (c) 2026 IQ.Lvbs. All rights reserved.
#pragma once

#include <Python.h>
#include <capnp/message.h>
#include <capnp/serialize.h>
#include <kj/debug.h>
#include <cstring>

inline PyObject* messageToPythonBytes(capnp::MessageBuilder& builder) {
  auto segments = builder.getSegmentsForOutput();
  auto words = capnp::computeSerializedSizeInWords(segments);
  KJ_REQUIRE(words <= static_cast<size_t>(PY_SSIZE_T_MAX) / sizeof(capnp::word));
  PyObject* result = PyBytes_FromStringAndSize(nullptr, words * sizeof(capnp::word));
  if (result == nullptr) return nullptr;
  char* data = PyBytes_AS_STRING(result);
  auto write32 = [data](size_t index, uint32_t value) {
    for (unsigned int byte = 0; byte < 4; ++byte) {
      data[index * 4 + byte] = static_cast<char>(value >> (byte * 8));
    }
  };
  write32(0, segments.size() - 1);
  for (size_t index = 0; index < segments.size(); ++index) {
    write32(index + 1, segments[index].size());
  }
  if (segments.size() % 2 == 0) write32(segments.size() + 1, 0);
  char* output = data + (segments.size() / 2 + 1) * sizeof(capnp::word);
  for (auto segment : segments) {
    auto size = segment.size() * sizeof(capnp::word);
    std::memcpy(output, segment.begin(), size);
    output += size;
  }
  return result;
}
