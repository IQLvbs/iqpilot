# -*- coding: utf-8 -*-
# distutils: language = c++
# cython: c_string_encoding=ascii, language_level=3
# Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/

import numpy as np
cimport numpy as cnp
from libc.string cimport memcpy
from libc.stdint cimport uintptr_t, uint8_t

from msgq.visionipc.visionipc cimport cl_mem
from msgq.visionipc.visionipc_pyx cimport VisionBuf, CLContext as BaseCLContext
from .iqmodel cimport CL_DEVICE_TYPE_DEFAULT, cl_get_device_id, cl_create_context, cl_release_context
from .iqmodel cimport mat3, ModelFrame as cppModelFrame, DrivingModelFrame as cppDrivingModelFrame, MonitoringModelFrame as cppMonitoringModelFrame


cdef class CLContext(BaseCLContext):
  def __cinit__(self):
    self.device_id = cl_get_device_id(CL_DEVICE_TYPE_DEFAULT)
    self.context = cl_create_context(self.device_id)

  def __dealloc__(self):
    if self.context:
      cl_release_context(self.context)

cdef class CLMem:
  @staticmethod
  cdef create(void * cmem):
    wrapper = CLMem()
    wrapper.mem = <cl_mem*> cmem
    return wrapper

  @property
  def mem_address(self):
    return <uintptr_t>(self.mem)

def cl_from_visionbuf(VisionBuf buf):
  return CLMem.create(<void*>&buf.buf.buf_cl)


cdef class ModelFrame:
  cdef cppModelFrame * frame
  cdef int buf_size

  def __dealloc__(self):
    del self.frame

  def prepare(self, VisionBuf buf, float[:] projection):
    cdef mat3 projection_matrix
    cdef cl_mem * output_frames
    memcpy(projection_matrix.v, &projection[0], 9*sizeof(float))
    output_frames = self.frame.prepare(buf.buf.buf_cl, buf.width, buf.height, buf.stride, buf.uv_offset, projection_matrix)
    return CLMem.create(output_frames)

  def buffer_from_cl(self, CLMem in_frames):
    cdef unsigned char * host_bytes
    host_bytes = self.frame.buffer_from_cl(in_frames.mem, self.buf_size)
    return np.asarray(<cnp.uint8_t[:self.buf_size]> host_bytes)


cdef class DrivingModelFrame(ModelFrame):
  cdef cppDrivingModelFrame * _frame

  def __cinit__(self, CLContext context, int buffer_length=2):
    self._frame = new cppDrivingModelFrame(context.device_id, context.context, buffer_length)
    self.frame = <cppModelFrame*>(self._frame)
    self.buf_size = self._frame.buf_size

cdef class MonitoringModelFrame(ModelFrame):
  cdef cppMonitoringModelFrame * _frame

  def __cinit__(self, CLContext context):
    self._frame = new cppMonitoringModelFrame(context.device_id, context.context)
    self.frame = <cppModelFrame*>(self._frame)
    self.buf_size = self._frame.buf_size
