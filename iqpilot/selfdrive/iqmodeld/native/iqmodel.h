/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
*/
#pragma once

#include <cassert>
#include <cfloat>
#include <cstdlib>
#include <memory>

#define CL_USE_DEPRECATED_OPENCL_1_2_APIS
#ifdef __APPLE__
#include <OpenCL/cl.h>
#else
#include <CL/cl.h>
#endif

#include "common/mat.h"
#include "iqpilot/selfdrive/iqmodeld/transforms/warp_geometry.h"
#include "iqpilot/selfdrive/iqmodeld/transforms/yuv.h"

class ModelFrame {
public:
  ModelFrame(cl_device_id device_id, cl_context context) {
    queue_ = CL_CHECK_ERR(clCreateCommandQueue(context, device_id, 0, &err));
  }
  virtual ~ModelFrame() {}
  virtual cl_mem *prepare(cl_mem yuv_cl, int frame_width, int frame_height, int frame_stride, int frame_uv_offset, const mat3 &projection) { return NULL; }

  uint8_t *buffer_from_cl(cl_mem *source_frames, int buffer_size) {
    CL_CHECK(clEnqueueReadBuffer(queue_, *source_frames, CL_TRUE, 0, buffer_size, host_bytes_.get(), 0, nullptr, nullptr));
    clFinish(queue_);
    return &host_bytes_[0];
  }

  int MODEL_WIDTH;
  int MODEL_HEIGHT;
  int MODEL_FRAME_SIZE;
  int buf_size;

protected:
  cl_mem luma_plane_cl_;
  cl_mem chroma_u_plane_cl_;
  cl_mem chroma_v_plane_cl_;
  PerspectiveWarpProgram warp_program_;
  cl_command_queue queue_;
  std::unique_ptr<uint8_t[]> host_bytes_;

  void bootstrap_warp(cl_device_id device_id, cl_context context, int model_width, int model_height) {
    luma_plane_cl_ = CL_CHECK_ERR(clCreateBuffer(context, CL_MEM_READ_WRITE, model_width * model_height, NULL, &err));
    chroma_u_plane_cl_ = CL_CHECK_ERR(clCreateBuffer(context, CL_MEM_READ_WRITE, (model_width / 2) * (model_height / 2), NULL, &err));
    chroma_v_plane_cl_ = CL_CHECK_ERR(clCreateBuffer(context, CL_MEM_READ_WRITE, (model_width / 2) * (model_height / 2), NULL, &err));
    perspective_warp_bootstrap(&warp_program_, context, device_id);
  }

  void shutdown_warp() {
    perspective_warp_shutdown(&warp_program_);
    CL_CHECK(clReleaseMemObject(chroma_v_plane_cl_));
    CL_CHECK(clReleaseMemObject(chroma_u_plane_cl_));
    CL_CHECK(clReleaseMemObject(luma_plane_cl_));
  }

  void enqueue_warp(cl_mem yuv_cl, int model_width, int model_height,
                    int frame_width, int frame_height, int frame_stride, int frame_uv_offset,
                    const mat3 &projection) {
    perspective_warp_enqueue(&warp_program_, queue_,
                             yuv_cl, frame_width, frame_height, frame_stride, frame_uv_offset,
                             luma_plane_cl_, chroma_u_plane_cl_, chroma_v_plane_cl_,
                             model_width, model_height, projection);
  }
};

class DrivingModelFrame : public ModelFrame {
public:
  DrivingModelFrame(cl_device_id device_id, cl_context context, uint8_t buffer_length);
  ~DrivingModelFrame();
  cl_mem *prepare(cl_mem yuv_cl, int frame_width, int frame_height, int frame_stride, int frame_uv_offset, const mat3 &projection);

  const int MODEL_WIDTH = 512;
  const int MODEL_HEIGHT = 256;
  const int MODEL_FRAME_SIZE = MODEL_WIDTH * MODEL_HEIGHT * 3 / 2;
  const int buf_size = MODEL_FRAME_SIZE * 2;
  const size_t frame_size_bytes = MODEL_FRAME_SIZE * sizeof(uint8_t);
  const uint8_t buffer_length;

private:
  PlanePackProgram plane_pack_program_;
  cl_mem rolling_frames_cl_;
  cl_mem latest_frame_cl_;
  cl_mem exported_frames_cl_;
  cl_buffer_region tail_region_;
};

class MonitoringModelFrame : public ModelFrame {
public:
  MonitoringModelFrame(cl_device_id device_id, cl_context context);
  ~MonitoringModelFrame();
  cl_mem *prepare(cl_mem yuv_cl, int frame_width, int frame_height, int frame_stride, int frame_uv_offset, const mat3 &projection);

  const int MODEL_WIDTH = 1440;
  const int MODEL_HEIGHT = 960;
  const int MODEL_FRAME_SIZE = MODEL_WIDTH * MODEL_HEIGHT;
  const int buf_size = MODEL_FRAME_SIZE;

private:
  cl_mem exported_frame_cl_;
};
