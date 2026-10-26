#include "selfdrive/dmonitoringmodeld/models/commonmodel.h"

#include <cmath>
#include <cstring>

#include "common/clutil.h"

MonitoringModelFrame::MonitoringModelFrame(cl_device_id device_id, cl_context context) : ModelFrame(device_id, context) {
  input_frames = std::make_unique<uint8_t[]>(buf_size);
  init_transform(device_id, context, MODEL_WIDTH, MODEL_HEIGHT);
}

cl_mem* MonitoringModelFrame::prepare(cl_mem yuv_cl, int frame_width, int frame_height, int frame_stride, int frame_uv_offset, const mat3& projection) {
  run_transform(yuv_cl, MODEL_WIDTH, MODEL_HEIGHT, frame_width, frame_height, frame_stride, frame_uv_offset, projection);
  clFinish(q);
  return &y_cl;
}

MonitoringModelFrame::~MonitoringModelFrame() {
  deinit_transform();
  CL_CHECK(clReleaseCommandQueue(q));
}
