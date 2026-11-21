"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from iqpilot.system.ui.iqwidgets.widgets.list_view import IQButtonAction


class WideButtonAction(IQButtonAction):
  def get_width_hint(self):
    return super().get_width_hint() + 1
