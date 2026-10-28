"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
from __future__ import annotations

import numpy as np
import pytest

from iqpilot.cereal import messaging
from iqpilot.selfdrive.iqmodeld.messaging import populate_iq_model_speed_limit


def test_cereal_publishes_declared_speed_limit_slice_and_zeros_otherwise():
  msg = messaging.new_message("iqDriveModelData")
  assert populate_iq_model_speed_limit(msg.iqDriveModelData, {"speed_limit": np.array([[31.0, 0.9, 1.0]])})
  assert msg.iqDriveModelData.speedLimitMps == pytest.approx(31.0)
  assert msg.iqDriveModelData.speedLimitProb == pytest.approx(0.9)
  assert msg.iqDriveModelData.speedLimitIsMph

  empty = messaging.new_message("iqDriveModelData")
  assert not populate_iq_model_speed_limit(empty.iqDriveModelData, {})
  assert empty.iqDriveModelData.speedLimitMps == 0.0
  assert empty.iqDriveModelData.speedLimitProb == 0.0
  assert not empty.iqDriveModelData.speedLimitIsMph


def test_publishes_nav_turn_probs_only_for_models_that_have_them():
  from iqpilot.selfdrive.iqmodeld.messaging import populate_iq_model_nav_turn
  msg = messaging.new_message("iqDriveModelData")
  assert not populate_iq_model_nav_turn(msg.iqDriveModelData, {})
  assert len(msg.iqDriveModelData.navTurnProbs) == 0
  assert not populate_iq_model_nav_turn(msg.iqDriveModelData, {"blinker_probabilities": np.array([[np.nan, 0.5, 0.5]])})
  assert populate_iq_model_nav_turn(msg.iqDriveModelData, {"blinker_probabilities": np.array([[0.1, 0.8, 0.1]])})
  assert list(msg.iqDriveModelData.navTurnProbs) == pytest.approx([0.1, 0.8, 0.1])
