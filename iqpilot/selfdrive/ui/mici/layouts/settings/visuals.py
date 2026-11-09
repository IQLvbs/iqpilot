"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""

from iqpilot.selfdrive.ui.mici.layouts.settings.iq_widgets import MappedParamToggle
from iqpilot.selfdrive.ui.mici.onroad.hud_renderer import BOTTOM_DISPLAY_PARAM, BottomDisplay
from iqpilot.selfdrive.ui.mici.widgets.stock_button import BigParamControl
from iqpilot.system.ui.widgets.scroller import NavScroller
from iqpilot.system.ui.lib.multilang import tr


class VisualsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._blind_spot = BigParamControl(tr("Blind Spot Warnings"), "IQBlindSpotAlerts")
    self._turn_signals = BigParamControl(tr("Turn Signals"), "IQBlinkerIndicators")
    self._bottom_display = MappedParamToggle(tr("Bottom UI Element"), BOTTOM_DISPLAY_PARAM,
                                             [tr("Off"), tr("Torque Bar"), tr("Lead Stats")],
                                             [mode.value for mode in BottomDisplay])

    self._toggles = [self._bottom_display, self._blind_spot, self._turn_signals]
    self._scroller.add_widgets(self._toggles)

  def show_event(self):
    super().show_event()
    for w in self._toggles:
      w.refresh()
