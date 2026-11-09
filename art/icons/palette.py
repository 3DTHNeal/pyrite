"""Colour ramps and the pixel helpers every icon shares.

Each ramp runs dark to light and has nine steps, so solids made of different materials can share one
shading index and still sit together in one picture.
"""

import numpy as np
from PIL import Image


def hexes(*colours: str) -> np.ndarray:
    return np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in colours], dtype=np.uint8)


BRASS = hexes("#140e06", "#2e2110", "#4d3915", "#73561f", "#9a7a2e", "#bf9e3f", "#dcc05e", "#f0dc93", "#fff7d6")  # pyrite
GOLD = hexes("#1c0c02", "#4a2404", "#7c3f05", "#ad6207", "#d88a0e", "#f0b42a", "#fbd453", "#ffeb98", "#fffbe6")
TARNISH = hexes("#0e0f12", "#2a2c31", "#4b4d50", "#6f6a5c", "#968a63", "#bba86e", "#d9c88a", "#efe6c4", "#fbf8ec")
IRON = hexes("#08090b", "#15171b", "#23262c", "#33373e", "#454a52", "#5b616a", "#767d86", "#9aa1a9", "#d4d8dc")
WATER = hexes("#0b1216", "#16242b", "#22363f", "#2f4a52", "#3f5f66", "#56777a", "#759490", "#9fb8b0", "#d7e6df")
PORCELAIN = hexes("#2a2724", "#57524b", "#8a847a", "#b3ada2", "#d0cbc0", "#e4e0d6", "#f1eee6", "#f9f7f1", "#ffffff")
STREAK = hexes("#050806", "#0e1510", "#17201a", "#202b23", "#2a362c", "#334035", "#3c4a3e", "#465547", "#506050")
CLAY = hexes("#1d0f0a", "#3b1f14", "#5e3321", "#7f4a31", "#9e6445", "#b98260", "#d1a382", "#e6c6aa", "#f6e6d6")
GLOW = hexes("#3a0702", "#6e1204", "#a52306", "#d8420a", "#f56d12", "#ff9a2a", "#ffc552", "#ffe58f", "#fffbe0")
BONE = hexes("#2b2722", "#4d463e", "#71685c", "#958b7d", "#b5ab9c", "#cec6b8", "#e2dcd0", "#f0ece4", "#fbf9f4")
ASH = hexes("#2b2722", "#4d463e", "#71685c", "#8a8072", "#a1978a", "#b5ab9c", "#c6bdae", "#d6cfc2", "#e6e0d6")  # the cupel's dish
BRICK = hexes("#1a0b08", "#3a1712", "#5a241b", "#7a3326", "#984433", "#b15a45", "#c7765f", "#dc9a85", "#efc4b5")
SPARK = hexes("#fffbe0", "#fff0a0", "#ffd04a", "#ffa21f", "#ec6a16", "#c23e12", "#7e2410")  # hot to cooling
INK = np.array([18, 12, 6], dtype=np.uint8)
WHITE_HOT = np.array([255, 253, 240, 255], np.uint8)
GLINT_EDGE = np.array([255, 236, 160, 255], np.uint8)


def outline(rgb: np.ndarray, mask: np.ndarray, color: np.ndarray = INK) -> np.ndarray:
    """RGBA of `rgb` inside `mask`, ringed by a 1-pixel ink line on the four sides."""
    m = mask.astype(bool)
    edge = np.zeros_like(m)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        edge |= np.roll(np.roll(m, dy, 0), dx, 1)
    edge &= ~m
    out = np.zeros(m.shape + (4,), np.uint8)
    out[..., :3] = rgb
    out[..., 3] = m * 255
    out[edge, :3] = color
    out[edge, 3] = 255
    return out


def shade_mask(m: np.ndarray, ramp: np.ndarray, mid: int, hi: int, lo: int) -> np.ndarray:
    """Flat-shade a 2D shape: lit along its top and left edges, shaded along its bottom and right."""
    rgb = np.zeros(m.shape + (3,), np.uint8)
    rgb[m] = ramp[mid]
    up, left = np.roll(m, 1, 0), np.roll(m, 1, 1)
    down, right = np.roll(m, -1, 0), np.roll(m, -1, 1)
    rgb[m & (~up | ~left)] = ramp[hi]
    rgb[m & (~down | ~right) & up & left] = ramp[lo]
    return rgb


def upscale(arr: np.ndarray, factor: int) -> Image.Image:
    im = Image.fromarray(arr)
    return im.resize((im.width * factor, im.height * factor), Image.NEAREST)


def strip(frames: list[np.ndarray]) -> Image.Image:
    """Frames side by side, the sprite strip the dashboard's CSS steps through."""
    h, w = frames[0].shape[:2]
    s = np.zeros((h, w * len(frames), 4), np.uint8)
    for i, f in enumerate(frames):
        s[:, i * w:(i + 1) * w] = f
    return Image.fromarray(s)
