"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""

import time
import numpy as np
import raylib_nb as rl
from iqpilot.cereal import messaging, log
from iqpilot.common.params import Params
from iqpilot.cereal.visionipc import VisionStreamType
from iqpilot.selfdrive.ui.ui_state import ui_state
from iqpilot.selfdrive.ui.mici.onroad.alert_renderer import AlertRenderer
from iqpilot.selfdrive.ui.mici.onroad.hud_renderer import HudRenderer
from iqpilot.selfdrive.ui.mici.onroad.model_renderer import ModelRenderer
from iqpilot.selfdrive.ui.mici.onroad.cameraview import CameraView
from iqpilot.system.ui.lib.application import FontWeight, gui_app, MousePos, MouseEvent, TextAlignment, TextAlignmentVertical
from iqpilot.system.ui.widgets.label import UnifiedLabel
from iqpilot.system.ui.widgets import Widget
from iqpilot.common.issue_debug import log_issue_limited
from iqpilot.common.filter_simple import BounceFilter, FirstOrderFilter
from iqpilot.common.transformations.camera import DEVICE_CAMERAS, DeviceCameraConfig, view_frame_from_device_frame
from iqpilot.common.transformations.orientation import rot_from_euler
from iqpilot.selfdrive.locationd.calibration_helpers import get_calibrated_rpy
from enum import IntEnum
from iqpilot.system.ui.lib.multilang import tr
from iqpilot.ui.mici.onroad.navigation import MiciNavigation

if gui_app.iqpilot_ui():
  from iqpilot.ui.mici.onroad.hud_renderer import IQMiciHudRenderer as HudRenderer
  from iqpilot.selfdrive.ui.ui_state import OnroadTimerStatus

ROAD_CAM = VisionStreamType.VISION_STREAM_ROAD
WIDE_CAM = VisionStreamType.VISION_STREAM_WIDE_ROAD
DEFAULT_DEVICE_CAMERA = DEVICE_CAMERAS["tici", "ar0231"]


class BookmarkState(IntEnum):
  HIDDEN = 0
  DRAGGING = 1
  TRIGGERED = 2


WIDE_CAM_MAX_SPEED = 5.0
ROAD_CAM_MIN_SPEED = 10.0

CAM_Y_OFFSET = 20
MICI_BORDER_THICKNESS = 50
MICI_BORDER_ROUNDNESS = 0.2 * 1.02
LONG_MODE_ICON_SIZE = 28
LONG_MODE_ICON_MARGIN = 18
VIGNETTE_WIDTH = 100
VIGNETTE_HEIGHT = 88
VIGNETTE_ALPHA = 235
VIGNETTE_SHAPE = 4.0
VIGNETTE_CORE = 0.1


def corner_vignette_alpha(width: int, height: int) -> np.ndarray:
  dx = (width - (np.arange(width) + 0.5)) / width
  dy = (height - (np.arange(height) + 0.5)) / height
  dist = (dx[None, :] ** VIGNETTE_SHAPE + dy[:, None] ** VIGNETTE_SHAPE) ** (1 / VIGNETTE_SHAPE)
  t = np.clip((dist - VIGNETTE_CORE) / (1 - VIGNETTE_CORE), 0.0, 1.0)
  return (VIGNETTE_ALPHA * (1 - t * t * (3 - 2 * t))).astype(np.uint8)


def corner_vignette_texture() -> rl.Texture:
  rgba = np.zeros((VIGNETTE_HEIGHT, VIGNETTE_WIDTH, 4), dtype=np.uint8)
  rgba[..., 3] = corner_vignette_alpha(VIGNETTE_WIDTH, VIGNETTE_HEIGHT)
  image = rl.gen_image_color(VIGNETTE_WIDTH, VIGNETTE_HEIGHT, rl.BLANK)
  try:
    texture = rl.load_texture_from_image(image)
  finally:
    rl.unload_image(image)
  rl.update_texture(texture, rgba.tobytes())
  rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
  return texture


class BookmarkIcon(Widget):
  PEEK_THRESHOLD = 50
  FULL_VISIBLE_OFFSET = 200
  HIDDEN_OFFSET = -50

  def __init__(self, bookmark_callback):
    super().__init__()
    self._bookmark_callback = bookmark_callback
    self._icon = gui_app.texture("icons_mici/onroad/bookmark.png", 180, 180)
    self._icon_fill = gui_app.texture("icons_mici/onroad/bookmark_fill.png", 180, 180)
    self._active_icon = self._icon
    self._offset_filter = BounceFilter(0.0, 0.1, 1 / gui_app.target_fps)

    self._interacting = False
    self._state = BookmarkState.HIDDEN
    self._swipe_start_x = 0.0
    self._swipe_current_x = 0.0
    self._is_swiping = False
    self._is_swiping_left: bool = False
    self._triggered_time: float = 0.0

  def is_swiping_left(self) -> bool:
    return self._is_swiping_left

  def interacting(self):
    interacting, self._interacting = self._interacting, False
    return interacting

  def _update_state(self):
    if self._state == BookmarkState.DRAGGING:
      swipe_offset = self._swipe_start_x - self._swipe_current_x
      swipe_offset = min(swipe_offset, self.FULL_VISIBLE_OFFSET + 50)
      self._offset_filter.update(swipe_offset)

    elif self._state == BookmarkState.TRIGGERED:
      self._offset_filter.update(self.FULL_VISIBLE_OFFSET)
      if rl.get_time() - self._triggered_time >= 1.5:
        self._state = BookmarkState.HIDDEN

    elif self._state == BookmarkState.HIDDEN:
      self._offset_filter.update(self.HIDDEN_OFFSET)

      if self._offset_filter.x < 1e-3:
        self._interacting = False
        self._active_icon = self._icon

  def _handle_mouse_event(self, mouse_event: MouseEvent):
    if not ui_state.started:
      return

    if mouse_event.left_pressed:
      self._swipe_start_x = mouse_event.pos.x
      self._swipe_current_x = mouse_event.pos.x
      self._is_swiping = True
      self._is_swiping_left = False
      self._state = BookmarkState.DRAGGING
      self._active_icon = self._icon

    elif mouse_event.left_down and self._is_swiping:
      self._swipe_current_x = mouse_event.pos.x
      swipe_offset = self._swipe_start_x - self._swipe_current_x
      self._is_swiping_left = swipe_offset > 0
      if self._is_swiping_left:
        self._interacting = True

    elif mouse_event.left_released:
      if self._is_swiping:
        swipe_distance = self._swipe_start_x - self._swipe_current_x

        if swipe_distance > self.PEEK_THRESHOLD:
          self._state = BookmarkState.TRIGGERED
          self._triggered_time = rl.get_time()
          self._active_icon = self._icon_fill
          self._bookmark_callback()
        else:
          self._state = BookmarkState.HIDDEN

        self._is_swiping = False
        self._is_swiping_left = False

  def _render(self, _):
    if self._offset_filter.x > 0:
      icon_x = self.rect.x + self.rect.width - round(self._offset_filter.x)
      icon_y = self.rect.y + (self.rect.height - self._active_icon.height) / 2
      rl.draw_texture(self._active_icon, int(icon_x), int(icon_y), rl.WHITE)


class AugmentedRoadView(CameraView):
  def __init__(self, bookmark_callback=None, stream_type: VisionStreamType = VisionStreamType.VISION_STREAM_ROAD):
    super().__init__("camerad", stream_type)
    self._set_placeholder_color(rl.BLACK)

    self.device_camera: DeviceCameraConfig | None = None
    self.view_from_calib = view_frame_from_device_frame.copy()
    self.view_from_wide_calib = view_frame_from_device_frame.copy()

    self._matrix_cache_key: tuple | None = None
    self._cached_matrix: np.ndarray | None = None
    self._content_rect = rl.Rectangle()

    self._bookmark_icon = BookmarkIcon(bookmark_callback)
    self._params = Params()
    self._iq_dynamic_mode: bool = False
    self._iq_dynamic_refresh: int = 0

    self._navigation = MiciNavigation()
    self._model_renderer = ModelRenderer()
    self._hud_renderer = HudRenderer()
    self._alert_renderer = AlertRenderer()
    self._nav_alpha = FirstOrderFilter(0.0, 0.15, 1 / gui_app.target_fps)
    self._experimental_txt = gui_app.texture("icons_mici/experimental_mode_mici.png",
                                             LONG_MODE_ICON_SIZE,
                                             LONG_MODE_ICON_SIZE)
    self._iqdynamic_txt = gui_app.texture("icons_mici/iqdynamic_mode_mici_28.png",
                                          LONG_MODE_ICON_SIZE,
                                          LONG_MODE_ICON_SIZE)
    self._iqstandard_txt = gui_app.texture("icons_mici/iqstandard_mode_mici_28.png",
                                           LONG_MODE_ICON_SIZE,
                                           LONG_MODE_ICON_SIZE)
    self._vignette = corner_vignette_texture()
    self._offroad_label = UnifiedLabel(tr("start the car to\nuse IQ.Pilot"), 54, FontWeight.DISPLAY,
                                       text_color=rl.Color(255, 255, 255, int(255 * 0.9)),
                                       alignment=TextAlignment.CENTER,
                                       alignment_vertical=TextAlignmentVertical.MIDDLE)

    self._pm = messaging.PubMaster(['uiDebug'])

  def is_swiping_left(self) -> bool:
    return self._bookmark_icon.is_swiping_left()

  def _update_state(self):
    super()._update_state()
    self._navigation.update()
    self._iq_dynamic_refresh -= 1
    if self._iq_dynamic_refresh <= 0:
      self._iq_dynamic_refresh = 60
      self._iq_dynamic_mode = self._params.get_bool("IQDynamicMode")

    if ui_state.panda_type == log.PandaState.PandaType.unknown:
      self._offroad_label.set_text(tr("system booting"))
    else:
      self._offroad_label.set_text(tr("start the car to\nuse IQ.Pilot"))

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if not self._bookmark_icon.interacting():
      super()._handle_mouse_release(mouse_pos)

  def _render(self, _):
    start_draw = time.monotonic()
    self._content_rect = rl.Rectangle(self.rect.x, self.rect.y, self.rect.width, self.rect.height)

    self._switch_stream_if_needed(ui_state.sm)
    self._update_calibration()

    rl.begin_scissor_mode(int(self._content_rect.x), int(self._content_rect.y), int(self._content_rect.width), int(self._content_rect.height))

    super()._render(self._content_rect)

    self._model_renderer.render(self._content_rect)

    alert_to_render, _ = self._alert_renderer.will_render()
    nav_alpha = self._nav_alpha.update(1.0 if ui_state.started and self._navigation.active and alert_to_render is None else 0.0)
    if ui_state.started:
      self._draw_long_mode_icon()
      self._navigation.render(self._content_rect, nav_alpha)
    self._hud_renderer.set_can_draw_top_icons(alert_to_render is None)
    if ui_state.started:
      self._alert_renderer.render(self._content_rect)
    self._hud_renderer.render(self._content_rect)

    rl.end_scissor_mode()

    self._draw_border()
    self._bookmark_icon.render(self.rect)

    draw_time_ms = (time.monotonic() - start_draw) * 1000
    if draw_time_ms > 40.0:
      log_issue_limited(
        "ui_draw_slow_mici",
        "ui",
        f"mici onroad draw slow drawTimeMillis={draw_time_ms:.2f} navActive={getattr(ui_state.sm['iqNavState'], 'active', False)}",
        interval_sec=1.0,
      )
    msg = messaging.new_message('uiDebug')
    msg.uiDebug.drawTimeMillis = draw_time_ms
    self._pm.send('uiDebug', msg)

    if not ui_state.started:
      rl.draw_rectangle(int(self.rect.x), int(self.rect.y), int(self.rect.width), int(self.rect.height), rl.Color(0, 0, 0, 175))
      self._offroad_label.render(self._content_rect)

  def _draw_long_mode_icon(self) -> None:
    if not ui_state.sm['carParams'].openpilotLongitudinalControl:
      return

    if ui_state.sm['selfdriveState'].experimentalMode:
      icon = self._iqdynamic_txt if self._iq_dynamic_mode else self._experimental_txt
    else:
      icon = self._iqstandard_txt

    right = self._content_rect.x + self._content_rect.width
    bottom = self._content_rect.y + self._content_rect.height
    rl.draw_texture(self._vignette, int(right - VIGNETTE_WIDTH), int(bottom - VIGNETTE_HEIGHT), rl.WHITE)
    pos_x = right - LONG_MODE_ICON_MARGIN - icon.width
    pos_y = bottom - LONG_MODE_ICON_MARGIN - icon.height
    rl.draw_texture(icon, int(pos_x), int(pos_y), rl.WHITE)

  def _draw_border(self):
    rl.draw_rectangle_rounded_lines_ex(self._content_rect, MICI_BORDER_ROUNDNESS, 10, MICI_BORDER_THICKNESS, rl.BLACK)

  def _switch_stream_if_needed(self, sm):
    if sm['selfdriveState'].experimentalMode and WIDE_CAM in self.available_streams:
      v_ego = sm['carState'].vEgo
      if v_ego < WIDE_CAM_MAX_SPEED:
        target = WIDE_CAM
      elif v_ego > ROAD_CAM_MIN_SPEED:
        target = ROAD_CAM
      else:
        target = self.stream_type
    else:
      target = ROAD_CAM

    self.switch_stream(target)

  def _update_calibration(self):
    sm = ui_state.sm
    if not self.device_camera and sm.seen['roadCameraState'] and sm.seen['deviceState']:
      self.device_camera = DEVICE_CAMERAS[(str(sm['deviceState'].deviceType), str(sm['roadCameraState'].sensor))]

    if not sm.seen["extrinsicsCalibration"]:
      return

    calib = sm['extrinsicsCalibration']
    calib_rpy = get_calibrated_rpy(calib)
    if calib_rpy is None:
      return

    prev_view_from_calib = self.view_from_calib.copy()
    prev_view_from_wide_calib = self.view_from_wide_calib.copy()
    device_from_calib = rot_from_euler(calib_rpy)
    self.view_from_calib = view_frame_from_device_frame @ device_from_calib

    if hasattr(calib, 'wideFromDeviceEuler') and len(calib.wideFromDeviceEuler) == 3:
      wide_from_device = rot_from_euler(calib.wideFromDeviceEuler)
      self.view_from_wide_calib = view_frame_from_device_frame @ wide_from_device @ device_from_calib

    if (not np.allclose(self.view_from_calib, prev_view_from_calib) or
        not np.allclose(self.view_from_wide_calib, prev_view_from_wide_calib)):
      self._matrix_cache_key = (0, 0, 0, self.stream_type, 0.0)
      self._cached_matrix = None

  def _calc_frame_matrix(self, rect: rl.Rectangle) -> np.ndarray:
    cache_key = (
      ui_state.sm.recv_frame['extrinsicsCalibration'],
      int(self._content_rect.width),
      int(self._content_rect.height),
      self.stream_type,
      round(ui_state.sm['carState'].vEgo, 1),
    )
    if cache_key == self._matrix_cache_key and self._cached_matrix is not None:
      return self._cached_matrix

    device_camera = self.device_camera or DEFAULT_DEVICE_CAMERA
    is_wide_camera = self.stream_type == WIDE_CAM
    intrinsic = device_camera.ecam.intrinsics if is_wide_camera else device_camera.fcam.intrinsics
    calibration = self.view_from_wide_calib if is_wide_camera else self.view_from_calib
    if is_wide_camera:
      zoom = 0.7 * 1.5
    else:
      zoom = np.interp(ui_state.sm['carState'].vEgo, [10, 30], [0.8, 1.0])

    inf_point = np.array([1000.0, 0.0, 0.0])
    calib_transform = intrinsic @ calibration
    kep = calib_transform @ inf_point

    w, h = self._content_rect.width, self._content_rect.height
    cx, cy = intrinsic[0, 2], intrinsic[1, 2]

    margin = 5
    max_x_offset = cx * zoom - w / 2 - margin
    max_y_offset = cy * zoom - h / 2 - margin

    try:
      if abs(kep[2]) > 1e-6:
        x_offset = np.clip((kep[0] / kep[2] - cx) * zoom, -max_x_offset, max_x_offset)
        y_offset = np.clip((kep[1] / kep[2] - cy) * zoom + CAM_Y_OFFSET, -max_y_offset, max_y_offset)
      else:
        x_offset, y_offset = 0, 0
    except (ZeroDivisionError, OverflowError):
      x_offset, y_offset = 0, 0

    self._matrix_cache_key = cache_key
    self._cached_matrix = np.array([
      [zoom * 2 * cx / w, 0, -x_offset / w * 2],
      [0, zoom * 2 * cy / h, -y_offset / h * 2],
      [0, 0, 1.0]
    ])

    video_transform = np.array([
      [zoom, 0.0, (w / 2 - x_offset) - (cx * zoom)],
      [0.0, zoom, (h / 2 - y_offset) - (cy * zoom)],
      [0.0, 0.0, 1.0]
    ])
    self._model_renderer.set_transform(video_transform @ calib_transform)

    return self._cached_matrix

  def show_event(self):
    if gui_app.iqpilot_ui():
      ui_state.reset_onroad_sleep_timer(OnroadTimerStatus.RESUME)

  def hide_event(self):
    if gui_app.iqpilot_ui():
      ui_state.reset_onroad_sleep_timer(OnroadTimerStatus.PAUSE)

