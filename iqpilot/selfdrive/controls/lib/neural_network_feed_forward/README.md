# Neural network feedforward (NNFF)

Open **Settings > Vehicle > NNFF Steering** while offroad (C3/C3X or comma 4). The card shows the matched model or the reason NNFF is unavailable. Changes are saved immediately and apply when the driving processes next initialize. NNFF defaults off and its selection survives manager restarts.

NNFF is available for the generic torque controller when a matching model is installed. Angle/curvature steering, PID steering, and the separate Volkswagen PQ/MQB controllers are not supported by this toggle. Enabling NNFF disables reduced steering feedback; enabling reduced steering feedback disables NNFF. A saved NNFF selection can always be switched off while offroad, including after its model becomes unavailable.

## Model files

Model files belong in `iqpilot/iqpilot_iq_nnff_models/neural_network_lateral_control/`, relative to the checkout root. This change does not distribute or download trained weights. An installation without models shows **no matching model installed**.

Models use an 18-input, one-output network with finite normalization values, positive standard deviations, and compatible dense layers. Selection accepts the identified vehicle family or an explicit entry in IQDBC's `car/torque_data/substitute.toml`. Similar names from unrelated vehicle families are not selected. A filename match and passing loader tests do not establish vehicle calibration or steering performance.

## Runtime behavior

The torque controller receives valid, fresh `modelV2` data and the same lateral delay used for its steering update. NNFF requires complete finite orientation and acceleration traces. It updates the shared PID once per cycle in torque units. Standard control uses acceleration units. Switching paths resets the integral and NNFF history and restores the appropriate bounds.

Missing, malformed, or stale inputs use standard torque control. An invalid model file or nonfinite inference output also falls back; an inference failure disables that model for the current drive. Stored user preference is preserved.

## Focused verification

```sh
python -m pytest -q \
  iqpilot/common/tests/test_nnff_params.py \
  iqpilot/selfdrive/controls/lib/neural_network_feed_forward/tests \
  iqpilot/selfdrive/controls/tests/test_nnff_controls.py \
  iqpilot/selfdrive/controls/tests/test_lateral_action_selection.py \
  iqpilot/selfdrive/controls/tests/test_lat_jerk_lowpass.py \
  iqpilot/selfdrive/controls/tests/test_hkg_reduced_torque_feedback.py \
  iqpilot/selfdrive/ui/tests/test_nnff_settings.py \
  iqpilot/selfdrive/ui/tests/test_nnff_big_settings.py \
  iqpilot/selfdrive/ui/tests/test_hkg_feedback_settings.py
```

The tests use isolated parameters. The model-loader suite uses synthetic weights when trained models are absent. These checks cover software behavior and do not constitute an on-road validation of any trained model.
