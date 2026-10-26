# Lateral Maneuvers Testing Tool

> [!WARNING]
> Use caution when using this tool.

Test your vehicle's lateral control tuning with this tool. The tool will test the vehicle's ability to follow a few lateral maneuvers and includes a tool to generate a report from the route.

## Instructions

1. Check out a development branch such as `master-mici` on your device. The toggle is hidden on release branches.
2. The full maneuver suite runs at 20 and 30 mph.
3. Enable "Lateral Maneuver Mode" in Settings > Developer on the device while offroad. Alternatively, set the parameter manually:

   ```sh
   echo -n 1 > /data/params/d/LateralManeuverMode
   ```

   To run only some of the maneuvers, set `LateralManeuverFilter` to a substring of their
   descriptions. Aborts mean a session often never reaches the later maneuvers, so target the one
   you need directly. Unset or unmatched runs the full suite.

   ```sh
   echo -n 'sine 0.5Hz 30mph' > /data/params/d/LateralManeuverFilter   # comma's published comparison
   echo -n '30mph'            > /data/params/d/LateralManeuverFilter   # all four 30 mph maneuvers
   ```

4. Turn your vehicle back on. You will see "Lateral Maneuver Mode".

5. Ensure the area ahead is clear, as IQ.Pilot will command lateral acceleration steps in this mode. Once you are ready, set ACC manually to the target speed shown on screen and let IQ.Pilot stabilize lateral. After 2 seconds of steady straight driving on a road under 250 m radius and under 6.8° of roll, the maneuver will begin automatically. IQ.Pilot lateral control stays engaged between maneuvers normally while waiting for the next maneuver's readiness conditions. The maneuver will be aborted and repeated if speed is out of range, the steering wheel or gas is touched, or IQ.Pilot disengages.

6. When the testing is complete, you'll see an alert that says "Maneuvers Finished." Complete the route by pulling over and turning off the vehicle.

7. Locate the route(s) — they will stand out with lots of orange intervals in their timeline. Ensure "All logs" show as "uploaded."

8. Gather the route ID and then run the report generator. The file will be exported to the same directory:

    ```sh
    $ python iqpilot/tools/maneuvers/lateral_report.py 98395b7c5b27882e/000001cc--5a73bde686

    processing report for KIA_EV6
    plotting maneuver: step right 20mph, runs: 3
    plotting maneuver: step left 20mph, runs: 3
    plotting maneuver: sine 0.5Hz 20mph, runs: 3
    plotting maneuver: step right 30mph, runs: 3

    Opening report: iqpilot/tools/maneuvers/reports/lateral/KIA_EV6_98395b7c5b27882e_000001cc--5a73bde686.html
    ```

   The IQ.Pilot `lateral_report.py` also takes a path to a local `rlog.zst` or a directory of them, supports
   auto-detection of lateral sweeps in any route without `alertDebug` markers (pass `--auto`), and ranks the
   top-N highest-peak sweeps by speed/peak filters. See `lateral_report.py --help`.

## Blog-style response plot

`lateral_response_plot.py` renders the "requested vs actual + 50% response time" figure comma
publishes, for one or more routes on the same axes:

```sh
$ python iqpilot/tools/maneuvers/lateral_response_plot.py '<route>' \
    --maneuver 'sine 0.5Hz 30mph' --label 'IQ.Lvbs angle — VW Golf MK7' --out response.png
```

Three stacked panels sharing a time axis: lateral acceleration (comma's panel, with the 50% marker),
steering wheel angle (commanded vs measured, the commanded trace only exists on angle-control cars),
and steering wheel rate. `--accel-only` drops to comma's single panel.

`controlsd` derives curvature as `-calc_curvature(steeringAngleDeg)`, so the raw wheel angle always
reads opposite to lateral acceleration. The angle and rate panels are flipped to match the
acceleration panel; pass `--raw-angle` to plot the raw log sign instead.

The 50% response time is only comparable between runs of the **same maneuver at the same speed**. A
step and a sine of equal amplitude do not produce comparable numbers: the step's request rises
instantly, so its 50% crossing measures rack rise time alone, while the 0.5 Hz sine's own request
takes ~0.167 s to reach 50%. comma's published 350 ms (ID.4) and 423 ms (Model Y) are both from the
0.5 Hz sine at 30 mph.

## Testing the tooling without a car

`simulate_lateral.py` runs `lateral_maneuversd` as a real process against a synthetic steering rack and writes an
rlog that `lateral_report.py` reads. Use it to verify the daemon and the report generator after changing either:

```sh
$ python iqpilot/tools/maneuvers/simulate_lateral.py --out /tmp/lat/rlog.zst
$ python iqpilot/tools/maneuvers/lateral_report.py /tmp/lat/rlog.zst
```

The full suite takes about 5 minutes of wall clock; `--max-maneuvers N` stops early.
