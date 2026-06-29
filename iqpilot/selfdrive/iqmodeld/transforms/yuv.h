/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
*/
#pragma once

#include "common/clutil.h"

typedef struct {
  int width;
  int height;
  cl_kernel luma_halves_kernel;
  cl_kernel chroma_plane_kernel;
  cl_kernel copy_bytes_kernel;
} PlanePackProgram;

void plane_pack_bootstrap(PlanePackProgram *program, cl_context ctx, cl_device_id device_id, int width, int height);
void plane_pack_shutdown(PlanePackProgram *program);

void plane_pack_enqueue(PlanePackProgram *program, cl_command_queue queue,
                        cl_mem y_plane_cl, cl_mem u_plane_cl, cl_mem v_plane_cl,
                        cl_mem packed_frame_cl);

void plane_copy_enqueue(PlanePackProgram *program, cl_command_queue queue, cl_mem src, cl_mem dst,
                        size_t src_offset, size_t dst_offset, size_t size);
