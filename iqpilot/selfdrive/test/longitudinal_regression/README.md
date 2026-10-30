# Longitudinal regression harness

Replays recorded rlogs through the real `LongitudinalPlanner` and scores the result.

```sh
python -m iqpilot.selfdrive.test.longitudinal_regression.cli <corpus> --out result.json --frames frames.json
python -m iqpilot.selfdrive.test.longitudinal_regression.compare_cli base_frames.json cand_frames.json --out compare.json
python -m iqpilot.selfdrive.test.longitudinal_regression.closed_loop <corpus> --windows closed_loop_windows.json --out cl.json
IQ_LONG_CORPUS=<corpus> pytest iqpilot/selfdrive/test/longitudinal_regression
```

`<corpus>` holds one directory per route named `<dongle>_<route>` with `<segment>_rlog.zst` files.
The corpus tests are not collected without `IQ_LONG_CORPUS`, so CI lanes that forbid skips are unaffected.

- `baseline_scorecards.json` freezes the scorecards of the planner before the lead MPC was removed from IQ.Pilot mode.
  Regenerate it only from a replay of that planner.
- `closed_loop_windows.json` lists 22 windows around hard-braking events in the 19 corpus routes. `closed_loop.py` replays the
  recorded model, radar and lead trajectory against a simulated ego driven by the planner's own output. The recorded model
  does not react to the simulated ego, so this is a counterfactual stress check and not a model-in-the-loop result.
- Open-loop replay cannot show what a changed plan would have done to the car; use the closed-loop windows or IQSim for that.
