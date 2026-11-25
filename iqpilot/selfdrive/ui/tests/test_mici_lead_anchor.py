from types import SimpleNamespace

import numpy as np
import pytest
import raylib_nb as rl

from iqpilot.selfdrive.ui.mici.onroad import model_renderer as module


def projecting_renderer(rect):
  renderer = object.__new__(module.ModelRenderer)
  renderer._rect = rect
  renderer._clip_region = rl.Rectangle(-module.CLIP_MARGIN, -module.CLIP_MARGIN,
                                       rect.width + 2 * module.CLIP_MARGIN, rect.height + 2 * module.CLIP_MARGIN)
  renderer._camera_offset = 0.0
  renderer._path_offset_z = 1.22
  renderer._path = module.ModelPoints(raw_points=np.column_stack((np.linspace(0, 100, 33), np.zeros(33), np.zeros(33))).astype(np.float32))
  f, cx, cy = 900.0, 238.0, 100.0
  renderer._car_space_transform = np.array([[cx, f, 0], [cy, 0, f], [1, 0, 0]], dtype=np.float32)
  return renderer


def radar(d_rel, y_rel=0.0):
  lead = SimpleNamespace(status=True, dRel=d_rel, yRel=y_rel, vRel=0.0)
  return SimpleNamespace(leadOne=lead, leadTwo=SimpleNamespace(status=False))


@pytest.mark.parametrize('slide_x', [-300.0, -120.0, 0.0, 200.0])
def test_lead_line_slides_with_the_view(slide_x):
  renderer = projecting_renderer(rl.Rectangle(0, 0, 476, 240))
  renderer._update_leads(radar(30.0))
  resting = renderer._screen_leads()[0].center

  renderer._rect = rl.Rectangle(slide_x, 0, 476, 240)
  slid = renderer._screen_leads()[0].center
  assert slid == pytest.approx((resting[0] + slide_x, resting[1]))


def test_lead_position_does_not_depend_on_where_the_view_was_when_computed():
  at_rest = projecting_renderer(rl.Rectangle(0, 0, 476, 240))
  mid_swipe = projecting_renderer(rl.Rectangle(-250, 0, 476, 240))
  for renderer in (at_rest, mid_swipe):
    renderer._update_leads(radar(30.0, y_rel=1.0))
  assert at_rest._lead_vehicles[0].center == pytest.approx(mid_swipe._lead_vehicles[0].center)
  assert at_rest._lead_vehicles[0].width == pytest.approx(mid_swipe._lead_vehicles[0].width)

