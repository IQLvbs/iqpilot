import pyray as rl
from iqpilot.selfdrive.ui.ui_state import ui_state
from iqpilot.system.ui.lib.application import gui_app
from iqpilot.system.ui.widgets import Widget


class ExpButton(Widget):
  def __init__(self, button_size: int, icon_size: int):
    super().__init__()
    self._engageable: bool = False

    self._mode_icons = {
      "STOCK ACC": gui_app.texture("icons/chffr_wheel.png", icon_size, icon_size),
      "IQ.PILOT": gui_app.texture("icons_mici/experimental_mode_tizi.png", icon_size, icon_size),
    }
    self._icon_size = icon_size
    self._rect = rl.Rectangle(0, 0, button_size, button_size)

  def _update_state(self) -> None:
    selfdrive_state = ui_state.sm["selfdriveState"]
    self._engageable = selfdrive_state.engageable or selfdrive_state.enabled

  def _render(self, rect: rl.Rectangle) -> None:
    label = "IQ.PILOT" if ui_state.has_longitudinal_control else "STOCK ACC"

    alpha = 170 if not self._engageable or self.is_pressed else 255
    icon_rect = rl.Rectangle(
      rect.x + (rect.width - self._icon_size) / 2,
      rect.y + (rect.height - self._icon_size) / 2,
      self._icon_size,
      self._icon_size,
    )
    texture = self._mode_icons[label]
    rl.draw_texture_pro(texture, rl.Rectangle(0, 0, texture.width, texture.height), icon_rect,
                        rl.Vector2(0, 0), 0, rl.Color(255, 255, 255, alpha))
