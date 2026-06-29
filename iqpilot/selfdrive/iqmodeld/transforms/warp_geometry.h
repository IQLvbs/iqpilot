/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
*/
#pragma once

#define CL_USE_DEPRECATED_OPENCL_1_2_APIS
#ifdef __APPLE__
#include <OpenCL/cl.h>
#else
#include <CL/cl.h>
#endif

#include "common/mat.h"

typedef struct {
  cl_kernel sampler_kernel;
  cl_mem luma_projection_cl;
  cl_mem chroma_projection_cl;
} PerspectiveWarpProgram;

void perspective_warp_bootstrap(PerspectiveWarpProgram *program, cl_context ctx, cl_device_id device_id);
void perspective_warp_shutdown(PerspectiveWarpProgram *program);

void perspective_warp_enqueue(PerspectiveWarpProgram *program, cl_command_queue queue,
                              cl_mem yuv, int in_width, int in_height, int in_stride, int in_uv_offset,
                              cl_mem out_y, cl_mem out_u, cl_mem out_v,
                              int out_width, int out_height,
                              const mat3 &projection);
