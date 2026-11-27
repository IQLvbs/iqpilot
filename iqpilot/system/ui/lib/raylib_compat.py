"""raylib 6 takes a Vector2 center in DrawCircleGradient and orders DrawRectangleGradientEx corners bottomRight before topRight; callers keep the old order."""
import raylib_nb as rl


def draw_circle_gradient(center_x: float, center_y: float, radius: float, inner, outer) -> None:
  rl.draw_circle_gradient(rl.Vector2(center_x, center_y), radius, inner, outer)


def draw_rectangle_gradient_ex(rec, top_left, bottom_left, top_right, bottom_right) -> None:
  rl.draw_rectangle_gradient_ex(rec, top_left, bottom_left, bottom_right, top_right)
