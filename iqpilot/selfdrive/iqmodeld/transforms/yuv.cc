/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
*/
#include "iqpilot/selfdrive/iqmodeld/transforms/yuv.h"

#include <assert.h>
#include <cstdio>
#include <cstring>

namespace {

void reset_program(PlanePackProgram *program) {
  memset(program, 0, sizeof(*program));
}

void build_plane_kernels(PlanePackProgram *program, cl_program cl_program_handle) {
  program->luma_halves_kernel = CL_CHECK_ERR(clCreateKernel(cl_program_handle, "packLumaHalves", &err));
  program->chroma_plane_kernel = CL_CHECK_ERR(clCreateKernel(cl_program_handle, "packChromaPlane", &err));
  program->copy_bytes_kernel = CL_CHECK_ERR(clCreateKernel(cl_program_handle, "copyPlaneBytes", &err));
}

void launch_linear_kernel(cl_command_queue queue, cl_kernel kernel, size_t work_items) {
  CL_CHECK(clEnqueueNDRangeKernel(queue, kernel, 1, nullptr, &work_items, nullptr, 0, 0, nullptr));
}

}  // namespace

void plane_pack_bootstrap(PlanePackProgram *program, cl_context ctx, cl_device_id device_id, int width, int height) {
  reset_program(program);
  program->width = width;
  program->height = height;

  char compiler_args[1024];
  snprintf(compiler_args, sizeof(compiler_args),
           "-cl-fast-relaxed-math -cl-denorms-are-zero "
           "-DTRANSFORMED_WIDTH=%d -DTRANSFORMED_HEIGHT=%d",
           width, height);

  cl_program program_handle = cl_program_from_file(ctx, device_id, LOADYUV_PATH, compiler_args);
  build_plane_kernels(program, program_handle);
  CL_CHECK(clReleaseProgram(program_handle));
}

void plane_pack_shutdown(PlanePackProgram *program) {
  CL_CHECK(clReleaseKernel(program->luma_halves_kernel));
  CL_CHECK(clReleaseKernel(program->chroma_plane_kernel));
  CL_CHECK(clReleaseKernel(program->copy_bytes_kernel));
}

void plane_pack_enqueue(PlanePackProgram *program, cl_command_queue queue,
                        cl_mem y_plane_cl, cl_mem u_plane_cl, cl_mem v_plane_cl,
                        cl_mem packed_frame_cl) {
  cl_int output_offset = 0;
  const size_t luma_work_items = (program->width * program->height) / 8;
  const size_t chroma_work_items = ((program->width / 2) * (program->height / 2)) / 8;

  CL_CHECK(clSetKernelArg(program->luma_halves_kernel, 0, sizeof(cl_mem), &y_plane_cl));
  CL_CHECK(clSetKernelArg(program->luma_halves_kernel, 1, sizeof(cl_mem), &packed_frame_cl));
  CL_CHECK(clSetKernelArg(program->luma_halves_kernel, 2, sizeof(cl_int), &output_offset));
  launch_linear_kernel(queue, program->luma_halves_kernel, luma_work_items);

  output_offset += program->width * program->height;
  CL_CHECK(clSetKernelArg(program->chroma_plane_kernel, 0, sizeof(cl_mem), &u_plane_cl));
  CL_CHECK(clSetKernelArg(program->chroma_plane_kernel, 1, sizeof(cl_mem), &packed_frame_cl));
  CL_CHECK(clSetKernelArg(program->chroma_plane_kernel, 2, sizeof(cl_int), &output_offset));
  launch_linear_kernel(queue, program->chroma_plane_kernel, chroma_work_items);

  output_offset += (program->width / 2) * (program->height / 2);
  CL_CHECK(clSetKernelArg(program->chroma_plane_kernel, 0, sizeof(cl_mem), &v_plane_cl));
  CL_CHECK(clSetKernelArg(program->chroma_plane_kernel, 1, sizeof(cl_mem), &packed_frame_cl));
  CL_CHECK(clSetKernelArg(program->chroma_plane_kernel, 2, sizeof(cl_int), &output_offset));
  launch_linear_kernel(queue, program->chroma_plane_kernel, chroma_work_items);
}

void plane_copy_enqueue(PlanePackProgram *program, cl_command_queue queue, cl_mem src, cl_mem dst,
                        size_t src_offset, size_t dst_offset, size_t size) {
  CL_CHECK(clSetKernelArg(program->copy_bytes_kernel, 0, sizeof(cl_mem), &src));
  CL_CHECK(clSetKernelArg(program->copy_bytes_kernel, 1, sizeof(cl_mem), &dst));
  CL_CHECK(clSetKernelArg(program->copy_bytes_kernel, 2, sizeof(cl_int), &src_offset));
  CL_CHECK(clSetKernelArg(program->copy_bytes_kernel, 3, sizeof(cl_int), &dst_offset));
  launch_linear_kernel(queue, program->copy_bytes_kernel, size / 8);
}
