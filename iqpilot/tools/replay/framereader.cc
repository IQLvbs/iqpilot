#include "tools/replay/framereader.h"

#include <map>
#include <memory>
#include <tuple>
#include <utility>

#include "common/util.h"
#include "common/yuv.h"
#include "tools/replay/util.h"
#include "system/hardware/hw.h"

#ifdef __APPLE__
#define HW_DEVICE_TYPE AV_HWDEVICE_TYPE_VIDEOTOOLBOX
#define HW_PIX_FMT AV_PIX_FMT_VIDEOTOOLBOX
#else
#define HW_DEVICE_TYPE AV_HWDEVICE_TYPE_CUDA
#define HW_PIX_FMT AV_PIX_FMT_CUDA
#endif

namespace {

enum AVPixelFormat get_hw_format(AVCodecContext *ctx, const enum AVPixelFormat *pix_fmts) {
  enum AVPixelFormat *hw_pix_fmt = reinterpret_cast<enum AVPixelFormat *>(ctx->opaque);
  for (const enum AVPixelFormat *p = pix_fmts; *p != -1; p++) {
    if (*p == *hw_pix_fmt) return *p;
  }
  rWarning("Please run replay with the --no-hw-decoder flag!");
  *hw_pix_fmt = AV_PIX_FMT_NONE;
  return AV_PIX_FMT_YUV420P;
}

struct DecoderManager {
  VideoDecoder *acquire(CameraType type, AVCodecParameters *codecpar, bool hw_decoder) {
    auto key = std::tuple(type, codecpar->width, codecpar->height);
    std::unique_lock lock(mutex_);
    if (auto it = decoders_.find(key); it != decoders_.end()) {
      return it->second.get();
    }

    std::unique_ptr<VideoDecoder> decoder;
    #ifndef __APPLE__
    if (!Hardware::PC() && hw_decoder) {
      decoder = std::make_unique<QcomVideoDecoder>();
    } else
    #endif
    {
      decoder = std::make_unique<FFmpegVideoDecoder>();
    }

    if (!decoder->open(codecpar, hw_decoder)) {
      decoder.reset(nullptr);
    }
    decoders_[key] = std::move(decoder);
    return decoders_[key].get();
  }

  std::mutex mutex_;
  std::map<std::tuple<CameraType, int, int>, std::unique_ptr<VideoDecoder>> decoders_;
};

DecoderManager decoder_manager;

}  // namespace

FrameReader::FrameReader() {
  av_log_set_level(AV_LOG_QUIET);
}

FrameReader::~FrameReader() {
  if (input_ctx) avformat_close_input(&input_ctx);
}

bool FrameReader::load(CameraType type, const std::string &url, bool no_hw_decoder, std::atomic<bool> *abort, bool local_cache, int chunk_size, int retries) {
  auto local_file_path = (url.find("https://") == 0 || url.find("http://") == 0) ? cacheFilePath(url) : url;
  if (!util::file_exists(local_file_path)) {
    FileReader f(local_cache, chunk_size, retries);
    if (f.read(url, abort).empty()) {
      return false;
    }
  }
  return loadFromFile(type, local_file_path, no_hw_decoder, abort);
}

bool FrameReader::loadFromFile(CameraType type, const std::string &file, bool no_hw_decoder, std::atomic<bool> *abort) {
  if (avformat_open_input(&input_ctx, file.c_str(), nullptr, nullptr) != 0 ||
      avformat_find_stream_info(input_ctx, nullptr) < 0) {
    rError("Failed to open input file or find video stream");
    return false;
  }
  input_ctx->probesize = 10 * 1024 * 1024;  // 10MB

  video_stream_idx_ = av_find_best_stream(input_ctx, AVMEDIA_TYPE_VIDEO, -1, -1, NULL, 0);
  if (video_stream_idx_ < 0) {
    rError("No video stream found in file");
    return false;
  }

  decoder_ = decoder_manager.acquire(type, input_ctx->streams[video_stream_idx_]->codecpar, !no_hw_decoder);
  if (!decoder_) {
    return false;
  }
  width = decoder_->width;
  height = decoder_->height;

  AVPacket pkt;
  packets_info.reserve(60 * 20);  // 20fps, one minute
  while (!(abort && *abort) && av_read_frame(input_ctx, &pkt) == 0) {
    if (pkt.stream_index == video_stream_idx_) {
      packets_info.emplace_back(PacketInfo{.flags = pkt.flags, .pos = pkt.pos, .ts = pkt.dts});
    }
    av_packet_unref(&pkt);
  }
  // IQ.Pilot camera files are (fragmented) MP4: rewinding the raw pb leaves the
  // mov demuxer's sample cursor at EOF, so rewind through the demuxer instead.
  // comma's raw HEVC bitstreams have no index; only the pb rewind works there.
  if (!packets_info.empty() &&
      avformat_seek_file(input_ctx, video_stream_idx_, INT64_MIN,
                         packets_info.front().ts, packets_info.front().ts, 0) < 0) {
    avformat_flush(input_ctx);
    avio_seek(input_ctx->pb, 0, SEEK_SET);
  }
  rInfo("frame index built: %zu packets, fmt=%s", packets_info.size(),
        input_ctx->iformat ? input_ctx->iformat->name : "?");
  return !packets_info.empty();
}

bool FrameReader::get(int idx, VisionBuf *buf) {
  if (!buf || idx < 0 || idx >= packets_info.size()) {
    return false;
  }
  return decoder_->decode(this, idx, buf);
}

// class VideoDecoder

FFmpegVideoDecoder::FFmpegVideoDecoder() {
  av_frame_ = av_frame_alloc();
  hw_frame_ = av_frame_alloc();
}

FFmpegVideoDecoder::~FFmpegVideoDecoder() {
  if (hw_device_ctx) av_buffer_unref(&hw_device_ctx);
  if (decoder_ctx) avcodec_free_context(&decoder_ctx);
  av_frame_free(&av_frame_);
  av_frame_free(&hw_frame_);
}

bool FFmpegVideoDecoder::open(AVCodecParameters *codecpar, bool hw_decoder) {
  const AVCodec *decoder = avcodec_find_decoder(codecpar->codec_id);
  if (!decoder) return false;

  decoder_ctx = avcodec_alloc_context3(decoder);
  if (!decoder_ctx || avcodec_parameters_to_context(decoder_ctx, codecpar) != 0) {
    rError("Failed to allocate or initialize codec context");
    return false;
  }
  width = (decoder_ctx->width + 3) & ~3;
  height = decoder_ctx->height;
  // frame-threaded software decode: single-threaded can't hold 2x1928x1208@20
  // on this SoC. The added output delay is absorbed by the EAGAIN-aware loop.
  decoder_ctx->thread_count = 3;
  decoder_ctx->thread_type = FF_THREAD_FRAME;

  if (hw_decoder && !initHardwareDecoder(HW_DEVICE_TYPE)) {
    rWarning("No device with hardware decoder found. fallback to CPU decoding.");
  }

  if (avcodec_open2(decoder_ctx, decoder, nullptr) < 0) {
    rError("Failed to open codec");
    return false;
  }
  return true;
}

bool FFmpegVideoDecoder::initHardwareDecoder(AVHWDeviceType hw_device_type) {
  const AVCodecHWConfig *config = nullptr;
  for (int i = 0; (config = avcodec_get_hw_config(decoder_ctx->codec, i)) != nullptr; i++) {
    if (config->methods & AV_CODEC_HW_CONFIG_METHOD_HW_DEVICE_CTX && config->device_type == hw_device_type) {
      hw_pix_fmt = config->pix_fmt;
      break;
    }
  }
  if (!config) {
    rWarning("Hardware configuration not found");
    return false;
  }

  int ret = av_hwdevice_ctx_create(&hw_device_ctx, hw_device_type, nullptr, nullptr, 0);
  if (ret < 0) {
    hw_pix_fmt = AV_PIX_FMT_NONE;
    rWarning("Failed to create specified HW device %d.", ret);
    return false;
  }

  decoder_ctx->hw_device_ctx = av_buffer_ref(hw_device_ctx);
  decoder_ctx->opaque = &hw_pix_fmt;
  decoder_ctx->get_format = get_hw_format;
  return true;
}

bool FFmpegVideoDecoder::decode(FrameReader *reader, int idx, VisionBuf *buf) {
  int current_idx = idx;
  if (idx != reader->prev_idx + 1) {
    if (idx > reader->prev_idx && idx - reader->prev_idx <= 300) {
      // forward catch-up: the decoder is already positioned at prev_idx+1, and
      // sequential decode is cheaper and (for raw H.264) more reliable than a
      // byte seek plus keyframe re-decode
      current_idx = reader->prev_idx + 1;
      reader->prev_idx = idx;
      goto read_packets;
    }
    // seeking to the nearest key frame
    for (int i = idx; i >= 0; --i) {
      if (reader->packets_info[i].flags & AV_PKT_FLAG_KEY) {
        current_idx = i;
        break;
      }
    }

    auto pos = reader->packets_info[current_idx].pos;
    int ret = avformat_seek_file(reader->input_ctx, 0, pos, pos, pos, AVSEEK_FLAG_BYTE);
    if (ret < 0) {
      // mp4 containers reject byte seeks; seek the keyframe by timestamp
      // through the mov index instead
      auto ts = reader->packets_info[current_idx].ts;
      ret = avformat_seek_file(reader->input_ctx, reader->video_stream_idx_, INT64_MIN, ts, ts, 0);
    }
    if (ret < 0) {
      rError("Failed to seek to byte position %lld: %d", pos, AVERROR(ret));
      return false;
    }
    avcodec_flush_buffers(decoder_ctx);
  }
  reader->prev_idx = idx;

read_packets:
  // H.264 has decoder delay: the first packets may legitimately yield no frame
  // yet (EAGAIN), and one packet can release several buffered frames. comma's
  // zero-delay HEVC never exercised either case.
  AVPacket pkt;
  int rf_ret;
  while ((rf_ret = av_read_frame(reader->input_ctx, &pkt)) >= 0) {
    if (pkt.stream_index != reader->video_stream_idx_) {
      av_packet_unref(&pkt);
      continue;
    }
    int ret = avcodec_send_packet(decoder_ctx, &pkt);
    av_packet_unref(&pkt);
    if (ret < 0) {
      rError("Error sending a packet for decoding: %d", ret);
      return false;
    }
    while ((ret = avcodec_receive_frame(decoder_ctx, av_frame_)) == 0) {
      AVFrame *frame = av_frame_;
      if (av_frame_->format == hw_pix_fmt) {
        if (av_hwframe_transfer_data(hw_frame_, av_frame_, 0) < 0) {
          rError("error transferring frame data from GPU to CPU");
          return false;
        }
        frame = hw_frame_;
      }
      if (current_idx++ == idx) {
        return copyBuffer(frame, buf);
      }
    }
    if (ret != AVERROR(EAGAIN)) {
      rError("avcodec_receive_frame error: %d", ret);
      return false;
    }
  }
  rError("Failed to find frame at index %d (read ret=%d)", idx, rf_ret);
  return false;
}

AVFrame *FFmpegVideoDecoder::decodeFrame(AVPacket *pkt) {
  int ret = avcodec_send_packet(decoder_ctx, pkt);
  if (ret < 0) {
    rError("Error sending a packet for decoding: %d", ret);
    return nullptr;
  }

  ret = avcodec_receive_frame(decoder_ctx, av_frame_);
  if (ret != 0) {
    rError("avcodec_receive_frame error: %d", ret);
    return nullptr;
  }

  if (av_frame_->format == hw_pix_fmt && av_hwframe_transfer_data(hw_frame_, av_frame_, 0) < 0) {
    rError("error transferring frame data from GPU to CPU");
    return nullptr;
  }
  return (av_frame_->format == hw_pix_fmt) ? hw_frame_ : av_frame_;
}

bool FFmpegVideoDecoder::copyBuffer(AVFrame *f, VisionBuf *buf) {
  if (hw_pix_fmt == HW_PIX_FMT) {
    for (int i = 0; i < height/2; i++) {
      memcpy(buf->y + (i*2 + 0)*buf->stride, f->data[0] + (i*2 + 0)*f->linesize[0], width);
      memcpy(buf->y + (i*2 + 1)*buf->stride, f->data[0] + (i*2 + 1)*f->linesize[0], width);
      memcpy(buf->uv + i*buf->stride, f->data[1] + i*f->linesize[1], width);
    }
  } else {
    yuv::i420_to_nv12(f->data[0], f->linesize[0],
                      f->data[1], f->linesize[1],
                      f->data[2], f->linesize[2],
                      buf->y, buf->stride,
                      buf->uv, buf->stride,
                      width, height);
  }
  return true;
}

#ifndef __APPLE__
QcomVideoDecoder::~QcomVideoDecoder() {
  if (bsf_) av_bsf_free(&bsf_);
}

bool QcomVideoDecoder::open(AVCodecParameters *codecpar, bool hw_decoder) {
  // msm_vidc decodes both; IQ.Pilot recordings are H.264 while comma's are HEVC
  uint32_t v4l2_fmt;
  if (codecpar->codec_id == AV_CODEC_ID_HEVC) {
    v4l2_fmt = V4L2_PIX_FMT_HEVC;
  } else if (codecpar->codec_id == AV_CODEC_ID_H264) {
    v4l2_fmt = V4L2_PIX_FMT_H264;
    if (codecpar->extradata && codecpar->extradata_size > 0) {
      // mp4 carries AVCC (length-prefixed NALs, headers out-of-band); the V4L2
      // decoder wants an Annex-B bitstream with in-band SPS/PPS
      const AVBitStreamFilter *f = av_bsf_get_by_name("h264_mp4toannexb");
      if (!f || av_bsf_alloc(f, &bsf_) < 0 ||
          avcodec_parameters_copy(bsf_->par_in, codecpar) < 0 || av_bsf_init(bsf_) < 0) {
        rError("failed to set up h264_mp4toannexb filter");
        return false;
      }
    }
  } else {
    rError("Hardware decoder only supports HEVC and H.264 codecs");
    return false;
  }
  width = codecpar->width;
  height = codecpar->height;
  msm_vidc.init(VIDEO_DEVICE, width, height, v4l2_fmt);
  return true;
}

bool QcomVideoDecoder::decode(FrameReader *reader, int idx, VisionBuf *buf) {
  int from_idx = idx;
  if (idx != reader->prev_idx + 1) {
    if (idx > reader->prev_idx && idx - reader->prev_idx <= 300) {
      // forward catch-up: the decoder is already positioned at prev_idx+1, and
      // sequential decode is cheaper and (for raw H.264) more reliable than a
      // byte seek plus keyframe re-decode
      from_idx = reader->prev_idx + 1;
    } else {
    // seeking to the nearest key frame
    for (int i = idx; i >= 0; --i) {
      if (reader->packets_info[i].flags & AV_PKT_FLAG_KEY) {
        from_idx = i;
        break;
      }
    }

    auto pos = reader->packets_info[from_idx].pos;
    int ret = avformat_seek_file(reader->input_ctx, 0, pos, pos, pos, AVSEEK_FLAG_BYTE);
    if (ret < 0) {
      // mp4 containers reject byte seeks; seek the keyframe by timestamp
      // through the mov index instead
      auto ts = reader->packets_info[from_idx].ts;
      ret = avformat_seek_file(reader->input_ctx, reader->video_stream_idx_, INT64_MIN, ts, ts, 0);
    }
    if (ret < 0) {
      rError("Failed to seek to byte position %lld: %d", pos, AVERROR(ret));
      return false;
    }
    }
  }
  reader->prev_idx = idx;
  bool result = false;
  AVPacket pkt;
  msm_vidc.avctx = reader->input_ctx;
  for (int i = from_idx; i <= idx; ++i) {
    if (av_read_frame(reader->input_ctx, &pkt) == 0) {
      if (bsf_ != nullptr) {
        if (av_bsf_send_packet(bsf_, &pkt) < 0 || av_bsf_receive_packet(bsf_, &pkt) < 0) {
          rError("h264_mp4toannexb failed at index %d", i);
          av_packet_unref(&pkt);
          return false;
        }
      }
      result = msm_vidc.decodeFrame(&pkt, buf) && (i == idx);
      av_packet_unref(&pkt);
    }
  }
  return result;
}
#endif
