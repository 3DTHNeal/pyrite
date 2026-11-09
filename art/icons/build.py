"""Draw Pyrite's icons and write them where the dashboard and the README use them.

    pip install -r art/icons/requirements.txt
    python art/icons/build.py

Writes tools/pyrite/static/icons/ (the favicon, the mark, its two animations and the stage icons) and
docs/images/ (the logo and the icon set for the README). Neither Pillow nor numpy is needed to run Pyrite:
only the PNGs this writes ship with it.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from palette import BRASS, outline, strip, upscale
from PIL import Image
from scenes import frames, still

ROOT = Path(__file__).resolve().parents[2]
STAGES = ["pan", "anvil", "streak", "furnace", "crucible", "balance", "cupel", "tarnished"]

# A 5 x 7 pixel face for the six letters of the name.
FONT = {
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "I": ["###", ".#.", ".#.", ".#.", ".#.", ".#.", "###"],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
}


def wordmark(text="PYRITE", scale=2):
    glyphs = [np.array([[c == "#" for c in row] for row in FONT[ch]]) for ch in text]
    m = np.zeros((7, sum(g.shape[1] for g in glyphs) + len(glyphs) - 1), bool)
    x = 0
    for g in glyphs:
        m[:, x:x + g.shape[1]] = g
        x += g.shape[1] + 1
    m = np.kron(m, np.ones((scale, scale), bool))
    h, w = m.shape
    rgb = np.where((np.arange(h) < h / 2)[:, None, None], BRASS[7], BRASS[5]).repeat(w, 1).astype(np.uint8)
    rgb[0] = BRASS[8]
    out = np.zeros((h + 1, w + 1, 4), np.uint8)
    out[1:, 1:][m] = (*BRASS[2], 255)  # drop shadow
    out[:h, :w][m] = np.dstack([rgb, np.full((h, w), 255, np.uint8)])[m]
    padded = np.zeros((h + 3, w + 3, 4), np.uint8)
    padded[1:-1, 1:-1] = out
    return outline(padded[..., :3], padded[..., 3] > 0)


def lockup(icon, gap=4, pad=4):
    word = wordmark()
    H = max(icon.shape[0], word.shape[0])
    out = np.zeros((H + 2 * pad, icon.shape[1] + gap + word.shape[1] + 2 * pad, 4), np.uint8)
    y = pad + (H - icon.shape[0]) // 2
    out[y:y + icon.shape[0], pad:pad + icon.shape[1]] = icon
    y = pad + (H - word.shape[0]) // 2 + 1
    x = pad + icon.shape[1] + gap
    out[y:y + word.shape[0], x:x + word.shape[1]] = word
    return out


def row(images, gap):
    h = max(i.shape[0] for i in images)
    out = np.zeros((h, sum(i.shape[1] for i in images) + gap * (len(images) - 1), 4), np.uint8)
    x = 0
    for i in images:
        out[h - i.shape[0]:, x:x + i.shape[1]] = i
        x += i.shape[1] + gap
    return out


def save(img, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    (img if isinstance(img, Image.Image) else Image.fromarray(img)).save(path, optimize=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=ROOT, help="the repository to write into (default: this one)")
    args = parser.parse_args(argv)
    icons, docs = args.out / "tools/pyrite/static/icons", args.out / "docs/images"

    marks = {N: still("mark", N) for N in (16, 32, 48)}
    # PNG favicons, not an .ico: the privacy check reads a PNG's metadata and refuses binary kinds it can't read.
    for N, img in marks.items():
        save(img, icons / f"mark-{N}.png")
    for name, file in (("mark", "mark-idle.png"), ("working", "mark-working.png")):
        fs, ms = frames(name, 32)
        save(strip(fs), icons / file)
        print(f"{file}: {len(fs)} frames, {ms} ms each")
    # 24 px beside a stage's name, and 48 px where a stage or a view is empty.
    for name in STAGES:
        save(still(name, 24), icons / f"{name}-24.png")
        save(still(name, 48), icons / f"{name}-48.png")
    # The name beside the mark in the dashboard's masthead, its letters 21 px tall to sit with the 32 px mark.
    save(wordmark(scale=3), icons / "wordmark.png")

    save(upscale(lockup(marks[32]), 4), docs / "pyrite-logo.png")
    save(upscale(row([still(name, 48) for name in STAGES], 8), 2), docs / "icon-set.png")
    print(f"Wrote {icons.relative_to(args.out)} and {docs.relative_to(args.out)}")


if __name__ == "__main__":
    sys.exit(main())
