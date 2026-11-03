"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import raylib_nb as rl
from iqpilot.selfdrive.ui.ui_state import UIStatus

BORDER_COLORS_IQ = {
  UIStatus.LAT_ONLY: rl.Color(0x0C, 0x94, 0x96, 0xFF),
  UIStatus.LONG_ONLY: rl.Color(0x96, 0x1C, 0xA8, 0xFF),
}
