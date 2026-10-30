import pytest
import itertools
from parameterized import parameterized_class

from iqpilot.cereal import log

from iqpilot.selfdrive.controls.lib.lead_assist.lead_assist import SAFE_TIME_GAP_FRACTION
from iqpilot.selfdrive.controls.lib.lead_assist.lead_plan import get_safe_obstacle_distance, get_stopped_equivalence_factor, get_T_FOLLOW
from iqpilot.selfdrive.test.longitudinal_maneuvers.maneuver import Maneuver


def desired_follow_distance(v_ego, v_lead, t_follow=None):
  if t_follow is None:
    t_follow = get_T_FOLLOW()
  return get_safe_obstacle_distance(v_ego, t_follow) - get_stopped_equivalence_factor(v_lead)

def run_following_distance_simulation(v_lead, t_end=100.0, personality=0, model="blind"):
  man = Maneuver(
    '',
    duration=t_end,
    initial_speed=float(v_lead),
    lead_relevancy=True,
    initial_distance_lead=100,
    speed_lead_values=[v_lead],
    breakpoints=[0.],
    personality=personality,
    model=model,
  )
  valid, output = man.evaluate()
  assert valid
  return output


PERSONALITIES = [log.LongitudinalPersonality.relaxed, log.LongitudinalPersonality.standard, log.LongitudinalPersonality.aggressive]


@parameterized_class(("personality", "speed"), itertools.product(PERSONALITIES, [10, 35]))
class TestE2eFollowingDistance:
  def test_lead_aware_model_keeps_its_own_gap(self):
    v_lead = float(self.speed)
    output = run_following_distance_simulation(v_lead, personality=self.personality, model="follow")
    natural_gap = 3.5 + 1.3 * v_lead
    assert output[-1, 2] - output[-1, 1] == pytest.approx(natural_gap, abs=0.1 * natural_gap + 1.0)

  def test_lead_blind_model_is_held_above_the_personality_floor(self):
    v_lead = float(self.speed)
    output = run_following_distance_simulation(v_lead, personality=self.personality, model="blind")
    late_gap = output[output[:, 0] > 50.0, 6]
    floor = SAFE_TIME_GAP_FRACTION * get_T_FOLLOW(self.personality) * v_lead
    assert late_gap.min() >= 0.5 * floor
