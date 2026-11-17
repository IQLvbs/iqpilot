import numpy as np
import raylib_nb as rl
from dataclasses import dataclass, field
from iqpilot.cereal import car
from iqpilot.common.filter_simple import FirstOrderFilter
from iqpilot.common.params import Params
from iqpilot.common.transformations.camera import DEVICE_CAMERAS
from iqpilot.selfdrive.locationd.calibration_helpers import get_render_path_height
from iqpilot.selfdrive.locationd.calibrationd import HEIGHT_INIT
from iqpilot.selfdrive.ui import UI_BORDER_SIZE
from iqpilot.selfdrive.ui.mici.onroad import blend_colors
from iqpilot.selfdrive.ui.onroad.model_renderer import LANE_LINE_COLORS as BIG_LANE_LINE_COLORS, LEAD_RADAR_TO_CAMERA, lead_line_width
from iqpilot.selfdrive.ui.ui_state import ui_state, UIStatus, log_param_from_bytes
from iqpilot.system.ui.lib.application import gui_app
from iqpilot.system.ui.lib.shader_polygon import draw_polygon, Gradient
from iqpilot.system.ui.widgets import Widget
from iqpilot.ui.onroad.model_renderer_helpers import BACKUP_PATH_WIDTH, ModelRendererHelpers
from iqpilot.ui.theme import NeonTheme

CLIP_MARGIN = 500
MIN_DRAW_DISTANCE = 10.0
MAX_DRAW_DISTANCE = 100.0
PATH_HALF_WIDTH = 0.9

THROTTLE_COLORS = [
  rl.Color(13, 248, 122, 102),
  rl.Color(114, 255, 92, 89),
  rl.Color(114, 255, 92, 0),
]

NO_THROTTLE_COLORS = [
  rl.Color(242, 242, 242, 102),
  rl.Color(242, 242, 242, 89),
  rl.Color(242, 242, 242, 0),
]

LANE_LINE_COLORS = {
  UIStatus.DISENGAGED: rl.Color(200, 200, 200, 255),
  UIStatus.OVERRIDE: rl.Color(255, 255, 255, 255),
  UIStatus.ENGAGED: rl.Color(0, 255, 64, 255),
}
HIGH_TORQUE_COLOR = rl.Color(255, 115, 0, 255)
THEMED_STATUSES = (UIStatus.ENGAGED, UIStatus.LAT_ONLY)

LEAD_LINE_GLOW = ((20, 8), (15, 15), (11, 28), (8, 48), (5, 100), (2, 255))
LEAD_LINE_FLAT = ((2, 255),)
LEAD_LINE_Y_MARGIN = 12

BIG_FOCAL_LENGTH = DEVICE_CAMERAS["tici", "ar0231"].fcam.focal_length
BIG_ROAD_ZOOM = 1.1
BIG_CAMERA_RECT_WIDTH = 2160 - 2 * UI_BORDER_SIZE


def theme_color(status: UIStatus) -> rl.Color | None:
  return NeonTheme.glow() if gui_app.iqpilot_ui() and status in THEMED_STATUSES else None


def big_lead_line_meters(d_rel: float) -> float:
  distance = d_rel + LEAD_RADAR_TO_CAMERA
  return lead_line_width(d_rel, BIG_CAMERA_RECT_WIDTH) * distance / (BIG_ROAD_ZOOM * BIG_FOCAL_LENGTH)


@dataclass
class ModelPoints:
  raw_points: np.ndarray = field(default_factory=lambda: np.empty((0, 3), dtype=np.float32))
  projected_points: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.float32))


@dataclass
class LeadVehicle:
  center: tuple[float, float] | None = None
  width: float = 0.0


class ModelRenderer(ModelRendererHelpers, Widget):
  def __init__(self):
    super().__init__()
    self._longitudinal_control = False
    self._experimental_mode = False
    self._blend_filter = FirstOrderFilter(1.0, 0.25, 1 / gui_app.target_fps)
    self._torque_filter = FirstOrderFilter(0, 0.1, 1 / gui_app.target_fps)
    self._lane_line_probs = np.zeros(4, dtype=np.float32)
    self._road_edge_stds = np.zeros(2, dtype=np.float32)
    self._lead_vehicles = [LeadVehicle(), LeadVehicle()]
    self._path_offset_z = HEIGHT_INIT[0]

    self._path = ModelPoints()
    self._lane_lines = [ModelPoints() for _ in range(4)]
    self._road_edges = [ModelPoints() for _ in range(2)]
    self._backup_path = ModelPoints()
    self._backup_alpha = FirstOrderFilter(0.0, 0.25, 1 / gui_app.target_fps)
    self._acceleration_x = np.empty((0,), dtype=np.float32)

    self._car_space_transform = np.zeros((3, 3), dtype=np.float32)
    self._transform_dirty = True
    self._clip_region = None

    self._set_render_preferences(ui_state.render_preferences)
    self._exp_gradient = Gradient(start=(0.0, 1.0), end=(0.0, 0.0), colors=[], stops=[])

    if (cp := log_param_from_bytes(Params(), "CarParams", car.CarParams)) is not None:
      self._longitudinal_control = cp.openpilotLongitudinalControl

  def set_transform(self, transform: np.ndarray):
    self._car_space_transform = transform.astype(np.float32)
    self._transform_dirty = True

  def _render(self, rect: rl.Rectangle):
    sm = ui_state.sm
    self._torque_filter.update(-sm['carOutput'].actuatorsOutput.torque)

    if (sm.recv_frame["extrinsicsCalibration"] < ui_state.started_frame or
        sm.recv_frame["modelV2"] < ui_state.started_frame):
      return

    self._clip_region = rl.Rectangle(-CLIP_MARGIN, -CLIP_MARGIN, rect.width + 2 * CLIP_MARGIN, rect.height + 2 * CLIP_MARGIN)
    self._experimental_mode = sm['selfdriveState'].experimentalMode
    self._path_offset_z = get_render_path_height(sm['extrinsicsCalibration'])
    if sm.updated['carParams']:
      self._longitudinal_control = sm['carParams'].openpilotLongitudinalControl

    radar_state = sm['radarState'] if sm.valid['radarState'] else None

    preferences_changed = self._set_render_preferences(ui_state.render_preferences)
    model_updated = sm.updated['modelV2'] or preferences_changed
    if model_updated or sm.updated['radarState'] or self._transform_dirty:
      if model_updated:
        self._update_raw_points(sm['modelV2'])
        self._update_backup_raw_points(sm['iqDriveModelData'].backupPath)

      path_x_array = self._path.raw_points[:, 0]
      if path_x_array.size == 0:
        return

      self._update_model(radar_state.leadOne if radar_state else None, path_x_array)
      self._update_backup_path()
      if radar_state is not None:
        self._update_leads(radar_state)
      self._transform_dirty = False

    if ui_state.status != UIStatus.DISENGAGED:
      self._draw_lane_lines()
      self._draw_backup_path((self._rect.x, self._rect.y))
      self._draw_path(sm)

    if radar_state is not None:
      self._draw_lead_indicator(self._screen_leads())

  def _update_model(self, lead, path_x_array):
    max_distance = np.clip(path_x_array[-1], MIN_DRAW_DISTANCE, MAX_DRAW_DISTANCE)
    max_idx = self._get_path_length_idx(self._lane_lines[0].raw_points[:, 0], max_distance)

    for i, lane_line in enumerate(self._lane_lines):
      width = 0.16 if i in (1, 2) else 0.12
      lane_line.projected_points = self._map_line_to_polygon(lane_line.raw_points, width * self._lane_line_probs[i], 0.0, max_idx)

    for road_edge in self._road_edges:
      road_edge.projected_points = self._map_line_to_polygon(road_edge.raw_points, 0.16, 0.0, max_idx)

    if lead and lead.status:
      lead_d = lead.dRel * 2.0
      max_distance = np.clip(lead_d - min(lead_d * 0.35, 10.0), 0.0, max_distance)

    max_idx = self._get_path_length_idx(path_x_array, max_distance)
    self._path.projected_points = self._map_line_to_polygon(
      self._path.raw_points, PATH_HALF_WIDTH, self._path_offset_z, max_idx, allow_invert=False
    )
    self._update_experimental_gradient()

  def _update_backup_path(self):
    backup_x = self._backup_path.raw_points[:, 0]
    if backup_x.size == 0:
      return
    max_distance = np.clip(backup_x[-1], MIN_DRAW_DISTANCE, MAX_DRAW_DISTANCE)
    self._backup_path.projected_points = self._map_line_to_polygon(
      self._backup_path.raw_points, BACKUP_PATH_WIDTH, self._path_offset_z,
      self._get_path_length_idx(backup_x, max_distance), allow_invert=False
    )

  def _update_experimental_gradient(self):
    if not self._experimental_mode:
      return

    path_pts = self._path.projected_points + np.array([self._rect.x, self._rect.y], dtype=np.float32)
    max_len = min(len(path_pts) // 2, len(self._acceleration_x))
    segment_colors = []
    gradient_stops = []

    i = 0
    while i < max_len:
      track_y = path_pts[i][1]
      if track_y < self._rect.y or track_y > (self._rect.y + self._rect.height):
        i += 1
        continue

      lin_grad_point = 1 - (track_y - self._rect.y) / self._rect.height
      path_hue = np.clip(60 + self._acceleration_x[i] * 35, 0, 120)
      saturation = min(abs(self._acceleration_x[i] * 1.5), 1)
      lightness = np.interp(saturation, [0.0, 1.0], [0.95, 0.62])
      alpha = np.interp(lin_grad_point, [0.75 / 2.0, 0.75], [0.4, 0.0])

      gradient_stops.append(lin_grad_point)
      segment_colors.append(self._hsla_to_color(path_hue / 360.0, saturation, lightness, alpha))
      i += 1 + (1 if (i + 2) < max_len else 0)

    self._exp_gradient.colors = segment_colors
    self._exp_gradient.stops = gradient_stops

  def _update_leads(self, radar_state):
    self._lead_vehicles = [LeadVehicle(), LeadVehicle()]
    points = self._path.raw_points
    for i, lead in enumerate((radar_state.leadOne, radar_state.leadTwo)):
      if not lead or not lead.status:
        continue
      distance = lead.dRel + LEAD_RADAR_TO_CAMERA
      z = float(np.interp(distance, points[:, 0], points[:, 2])) if len(points) else 0.0
      z += self._path_offset_z
      point = self._map_to_screen(distance, -lead.yRel, z)
      if point is None:
        continue
      half = big_lead_line_meters(lead.dRel) / 2
      ends = self._project_car_points(np.array([[distance, -lead.yRel - half, z],
                                                [distance, -lead.yRel + half, z]], dtype=np.float32))
      if not np.all(np.abs(ends[2]) > 1e-6):
        continue
      width = min(float(abs(ends[0, 0] / ends[2, 0] - ends[0, 1] / ends[2, 1])), self._rect.width)
      x = max(width / 2, min(point[0], self._rect.width - width / 2))
      y = max(LEAD_LINE_Y_MARGIN, min(point[1], self._rect.height - LEAD_LINE_Y_MARGIN))
      self._lead_vehicles[i] = LeadVehicle(center=(float(x), float(y)), width=width)

  def _screen_leads(self) -> list[LeadVehicle]:
    return [LeadVehicle(center=(lead.center[0] + self._rect.x, lead.center[1] + self._rect.y), width=lead.width)
            if lead.center is not None else lead for lead in self._lead_vehicles]

  def _get_ll_color(self, prob: float, adjacent: bool, left: bool):
    alpha = int(np.clip(prob, 0.0, 0.7) * 255)
    if ui_state.status == UIStatus.DISENGAGED:
      return rl.Color(0, 0, 0, alpha)
    if not adjacent:
      return rl.Color(255, 255, 255, alpha)

    base = theme_color(ui_state.status) or LANE_LINE_COLORS.get(ui_state.status, LANE_LINE_COLORS[UIStatus.DISENGAGED])
    color = rl.Color(base.r, base.g, base.b, alpha)

    torque = self._torque_filter.x
    if abs(torque) > 0.6 and left == (torque > 0):
      warn = rl.Color(HIGH_TORQUE_COLOR.r, HIGH_TORQUE_COLOR.g, HIGH_TORQUE_COLOR.b, alpha)
      color = blend_colors(color, warn, np.interp(abs(torque), [0.6, 0.8], [0.0, 1.0]))
    return color

  def _draw_lane_lines(self):
    offset = np.array([self._rect.x, self._rect.y], dtype=np.float32)
    for i, lane_line in enumerate(self._lane_lines):
      if lane_line.projected_points.size == 0:
        continue
      color = self._get_ll_color(float(self._lane_line_probs[i]), i in (1, 2), i in (0, 1))
      draw_polygon(self._rect, lane_line.projected_points + offset, color)

    for i, road_edge in enumerate(self._road_edges):
      if road_edge.projected_points.size == 0:
        continue
      color = self._get_ll_color(float(1.0 - self._road_edge_stds[i]), float(self._lane_line_probs[i + 1]) < 0.25, i == 0)
      draw_polygon(self._rect, road_edge.projected_points + offset, color)

  def _draw_path(self, sm):
    if not self._path.projected_points.size:
      return

    path_pts = self._path.projected_points + np.array([self._rect.x, self._rect.y], dtype=np.float32)
    allow_throttle = sm['longitudinalPlan'].allowThrottle or not self._longitudinal_control
    self._blend_filter.update(int(allow_throttle))

    if ui_state.status == UIStatus.DISENGAGED:
      draw_polygon(self._rect, path_pts, rl.Color(0, 0, 0, 90))
    elif self._experimental_mode:
      if len(self._exp_gradient.colors) > 1:
        draw_polygon(self._rect, path_pts, gradient=self._exp_gradient)
      else:
        draw_polygon(self._rect, path_pts, rl.Color(255, 255, 255, 30))
    else:
      blend_factor = round(self._blend_filter.x * 100) / 100
      colors = self._blend_colors(NO_THROTTLE_COLORS, THROTTLE_COLORS, blend_factor)
      draw_polygon(self._rect, path_pts, gradient=Gradient(start=(0.0, 1.0), end=(0.0, 0.0), colors=colors, stops=[0.0, 0.5, 1.0]))

  def _draw_lead_indicator(self, leads: list[LeadVehicle]):
    status = ui_state.status
    base = theme_color(status) or BIG_LANE_LINE_COLORS.get(status, BIG_LANE_LINE_COLORS[UIStatus.DISENGAGED])
    layers = LEAD_LINE_FLAT if status in (UIStatus.DISENGAGED, UIStatus.OVERRIDE) else LEAD_LINE_GLOW

    for lead in leads:
      if lead.center is None:
        continue
      cx, cy = lead.center
      for height, alpha in layers:
        rl.draw_rectangle_rounded(rl.Rectangle(cx - lead.width / 2, cy - height / 2, lead.width, height),
                                   1.0, 8, rl.Color(base.r, base.g, base.b, alpha))

  @staticmethod
  def _get_path_length_idx(pos_x_array: np.ndarray, path_height: float) -> int:
    if len(pos_x_array) == 0:
      return 0
    indices = np.where(pos_x_array <= path_height)[0]
    return indices[-1] if indices.size > 0 else 0

  def _map_line_to_polygon(self, line: np.ndarray, y_off: float, z_off: float, max_idx: int, allow_invert: bool = True) -> np.ndarray:
    empty = np.empty((0, 2), dtype=np.float32)
    if line.shape[0] == 0:
      return empty

    points = line[:max_idx + 1]
    points = points[points[:, 0] >= 0]
    if points.shape[0] == 0:
      return empty

    n = points.shape[0]
    offsets = np.array([[0, -y_off, z_off], [0, y_off, z_off]], dtype=np.float32)
    points_3d = (points[None, :, :] + offsets[:, None, :]).reshape(2 * n, 3)
    proj = self._project_car_points(points_3d).reshape(3, 2, n)
    left_proj = proj[:, 0, :]
    right_proj = proj[:, 1, :]

    valid_proj = (np.abs(left_proj[2]) >= 1e-6) & (np.abs(right_proj[2]) >= 1e-6)
    if not np.any(valid_proj):
      return empty

    left_screen = left_proj[:2, valid_proj] / left_proj[2, valid_proj][None, :]
    right_screen = right_proj[:2, valid_proj] / right_proj[2, valid_proj][None, :]

    clip = self._clip_region
    x_min, x_max = clip.x, clip.x + clip.width
    y_min, y_max = clip.y, clip.y + clip.height
    in_clip = ((left_screen[0] >= x_min) & (left_screen[0] <= x_max) & (left_screen[1] >= y_min) & (left_screen[1] <= y_max) &
               (right_screen[0] >= x_min) & (right_screen[0] <= x_max) & (right_screen[1] >= y_min) & (right_screen[1] <= y_max))
    if not np.any(in_clip):
      return empty

    left_screen = left_screen[:, in_clip]
    right_screen = right_screen[:, in_clip]

    if not allow_invert and left_screen.shape[1] > 1:
      y = left_screen[1, :]
      keep = y == np.minimum.accumulate(y)
      left_screen = left_screen[:, keep]
      right_screen = right_screen[:, keep]

    return np.vstack((left_screen.T, right_screen[:, ::-1].T)).astype(np.float32)
