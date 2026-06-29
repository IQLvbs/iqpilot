/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
*/
#include "iqpilot/selfdrive/iqmodeld/native/iqmodel.h"

#include <cstring>

#include "common/clutil.h"

namespace {

void roll_frame_history(cl_command_queue queue, cl_mem frame_history, uint8_t frame_count, size_t frame_size_bytes) {
  for (int index = 0; index < (frame_count - 1); index++) {
    CL_CHECK(clEnqueueCopyBuffer(queue, frame_history, frame_history,
                                 (index + 1) * frame_size_bytes, index * frame_size_bytes,
                                 frame_size_bytes, 0, nullptr, nullptr));
  }
}

}  // namespace

DrivingModelFrame::DrivingModelFrame(cl_device_id device_id, cl_context context, uint8_t buffer_length)
    : ModelFrame(device_id, context), buffer_length(buffer_length) {
  host_bytes_ = std::make_unique<uint8_t[]>(buf_size);
  exported_frames_cl_ = CL_CHECK_ERR(clCreateBuffer(context, CL_MEM_READ_WRITE, buf_size, NULL, &err));
  rolling_frames_cl_ = CL_CHECK_ERR(clCreateBuffer(context, CL_MEM_READ_WRITE, buffer_length * frame_size_bytes, NULL, &err));

  tail_region_.origin = (buffer_length - 1) * frame_size_bytes;
  tail_region_.size = frame_size_bytes;
  latest_frame_cl_ = CL_CHECK_ERR(clCreateSubBuffer(rolling_frames_cl_, CL_MEM_READ_WRITE, CL_BUFFER_CREATE_TYPE_REGION, &tail_region_, &err));

  plane_pack_bootstrap(&plane_pack_program_, context, device_id, MODEL_WIDTH, MODEL_HEIGHT);
  bootstrap_warp(device_id, context, MODEL_WIDTH, MODEL_HEIGHT);
}

cl_mem *DrivingModelFrame::prepare(cl_mem yuv_cl, int frame_width, int frame_height, int frame_stride, int frame_uv_offset, const mat3 &projection) {
  enqueue_warp(yuv_cl, MODEL_WIDTH, MODEL_HEIGHT, frame_width, frame_height, frame_stride, frame_uv_offset, projection);
  roll_frame_history(queue_, rolling_frames_cl_, buffer_length, frame_size_bytes);
  plane_pack_enqueue(&plane_pack_program_, queue_, luma_plane_cl_, chroma_u_plane_cl_, chroma_v_plane_cl_, latest_frame_cl_);
  plane_copy_enqueue(&plane_pack_program_, queue_, rolling_frames_cl_, exported_frames_cl_, 0, 0, frame_size_bytes);
  plane_copy_enqueue(&plane_pack_program_, queue_, latest_frame_cl_, exported_frames_cl_, 0, frame_size_bytes, frame_size_bytes);

  clFinish(queue_);
  return &exported_frames_cl_;
}

DrivingModelFrame::~DrivingModelFrame() {
  shutdown_warp();
  plane_pack_shutdown(&plane_pack_program_);
  CL_CHECK(clReleaseMemObject(rolling_frames_cl_));
  CL_CHECK(clReleaseMemObject(latest_frame_cl_));
  CL_CHECK(clReleaseCommandQueue(queue_));
}

MonitoringModelFrame::MonitoringModelFrame(cl_device_id device_id, cl_context context) : ModelFrame(device_id, context) {
  host_bytes_ = std::make_unique<uint8_t[]>(buf_size);
  exported_frame_cl_ = CL_CHECK_ERR(clCreateBuffer(context, CL_MEM_READ_WRITE, buf_size, NULL, &err));
  bootstrap_warp(device_id, context, MODEL_WIDTH, MODEL_HEIGHT);
}

cl_mem *MonitoringModelFrame::prepare(cl_mem yuv_cl, int frame_width, int frame_height, int frame_stride, int frame_uv_offset, const mat3 &projection) {
  enqueue_warp(yuv_cl, MODEL_WIDTH, MODEL_HEIGHT, frame_width, frame_height, frame_stride, frame_uv_offset, projection);
  clFinish(queue_);
  return &luma_plane_cl_;
}

MonitoringModelFrame::~MonitoringModelFrame() {
  shutdown_warp();
  CL_CHECK(clReleaseMemObject(exported_frame_cl_));
  CL_CHECK(clReleaseCommandQueue(queue_));
}
