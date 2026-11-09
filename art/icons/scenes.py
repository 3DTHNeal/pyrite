"""The icons: Pyrite's mark and one icon for each stage of the job pipeline, read as a fire assay.

Every icon shares one camera family (yaw 30 degrees), one light, one ink outline and one crystal in one pose,
and is fitted to the same margins. `still` draws an icon at a size; `frames` draws its animation, if it has one.
"""

import numpy as np
from palette import ASH, BONE, BRASS, BRICK, CLAY, GLINT_EDGE, GLOW, GOLD, INK, IRON, PORCELAIN, SPARK, STREAK, TARNISH, WATER, WHITE_HOT, outline, shade_mask
from PIL import Image, ImageDraw
from render import Solid, box, frustum, glint_point, pixel_art, pyritohedron, render, rot, sphere

YAW = 30
CRYSTAL = pyritohedron(0.5)
CRYSTAL_POSE = rot(-10, -8)  # the one pose the crystal takes in every icon
BEAD = sphere()
FREQ = {16: 2.0, 24: 2.5, 32: 3.0, 48: 4.0}  # striations per unit, so each size keeps bands 2-3 pixels wide


def view(pitch):
    return rot(YAW, pitch)


def smooth(ramp):
    return {"ramp": ramp, "stripes": False}


def crystal(t=(0, 0, 0), scale=1.0, ramp=None, tilt=None):
    return Solid(CRYSTAL, R=(np.eye(3) if tilt is None else tilt) @ CRYSTAL_POSE, t=t, scale=scale, ramp=ramp)


def resting_on(y_surface, scale, sink=0.12):
    """The crystal's centre height when it sits on a surface at y_surface, sunk in a little."""
    return y_surface - scale * 1.5 + sink


def glow(k):
    """The melt's ramp for flicker frame k, every step nudged a little up or down."""
    jitter = [0, 1, 0, -1, 0, 1, 1, 0][k % 8]
    return GLOW[np.clip(np.arange(9) + jitter, 0, 8)]


# Each builder returns (solids, focus): focus is what a glint, a spark or a bubble attaches to.
def mark():
    c = crystal()
    return [c], [c]


def tarnished():
    c = crystal(ramp=TARNISH)
    return [c], [c]


def pan():
    rim = Solid(frustum(1.0, 0.3, 1.5, -0.12, 24), **smooth(IRON))
    water = Solid(frustum(1.32, -0.12, 1.32, -0.17, 24), **smooth(WATER))
    c = crystal(t=(0.05, resting_on(-0.17, 0.5, 0.28), 0.0), scale=0.5)
    return [rim, water, c], [c]


def streak():
    tile = Solid(box(-1.2, 1.2, 0.0, 0.2, -0.62, 0.62), **smooth(PORCELAIN))
    # Pyrite's streak is greenish black, where gold's is gold: wide where the stroke began, narrowing toward the crystal.
    line = Solid(np.array([(x, y, z) for x in (-1.0,) for y in (-0.03, 0.0) for z in (-0.34, 0.34)] +
                          [(x, y, z) for x in (0.45,) for y in (-0.03, 0.0) for z in (-0.18, 0.18)], float), **smooth(STREAK))
    c = crystal(t=(0.8, resting_on(0.0, 0.36, 0.14), 0.0), scale=0.36, tilt=rot(0, 0, 16))
    return [tile, line, c], [c]


def anvil():
    iron = smooth(IRON)
    foot = np.array([(sx * 0.85, 0.95, sz * 0.55) for sx in (-1, 1) for sz in (-1, 1)] +
                    [(sx * 0.55, 0.6, sz * 0.38) for sx in (-1, 1) for sz in (-1, 1)], float)
    horn = np.array([(-0.85, -0.3, -0.36), (-0.85, -0.3, 0.36), (-0.85, 0.1, -0.3), (-0.85, 0.1, 0.3),
                     (-1.8, -0.24, 0.0), (-1.75, -0.2, 0.04)], float)
    c = crystal(t=(0.2, resting_on(-0.3, 0.52), 0.0), scale=0.52)
    return [Solid(foot, **iron), Solid(box(-0.36, 0.36, 0.15, 0.62, -0.27, 0.27), **iron),
            Solid(box(-0.85, 1.0, -0.3, 0.15, -0.42, 0.42), **iron), Solid(horn, **iron), c], [c]


def furnace(k=0):
    brick = smooth(BRICK)
    flue = Solid(box(-0.35, 0.35, -1.25, -0.55, -0.3, 0.3), **brick)
    return [Solid(box(-0.9, 0.9, -0.55, 0.95, -0.8, 0.8), **brick), flue,
            Solid(box(-0.5, 0.5, -0.05, 0.62, -0.86, -0.79), **smooth(glow(k)))], [flue]


def crucible(k=0):
    melt = Solid(frustum(0.74, -0.68, 0.74, -0.73, 16), **smooth(glow(k)))
    return [Solid(frustum(0.55, 0.75, 0.86, -0.7, 16), **smooth(CLAY)), melt], [melt]


def cupel():
    cup = np.array([(sx * 0.95, 0.45, sz * 0.95) for sx in (-1, 1) for sz in (-1, 1)] +
                   [(sx * 1.05, -0.35, sz * 1.05) for sx in (-1, 1) for sz in (-1, 1)], float)
    bead = Solid(BEAD, t=(0.05, -0.38 - 0.26 + 0.05, 0.0), scale=0.26, **smooth(GOLD))
    return [Solid(cup, **smooth(BONE)), Solid(frustum(0.7, -0.35, 0.7, -0.38, 16), **smooth(ASH)), bead], [bead]


# name: (builder, camera pitch, fit box as fractions of the frame: width, height, centre x, centre y)
ICONS = {
    "mark": (mark, 30, (0.84, 0.84, 0.5, 0.5)),
    "working": (mark, 30, (0.6, 0.6, 0.34, 0.46)),  # room on the right for sparks
    "pan": (pan, 40, (0.92, 0.8, 0.5, 0.5)),
    "anvil": (anvil, 26, (0.74, 0.72, 0.4, 0.58)),
    "streak": (streak, 36, (0.92, 0.8, 0.5, 0.52)),
    "furnace": (furnace, 24, (0.78, 0.8, 0.5, 0.56)),  # room above the flue for embers
    "crucible": (crucible, 30, (0.72, 0.78, 0.5, 0.58)),
    "balance": (None, 0, None),
    "cupel": (cupel, 36, (0.9, 0.78, 0.5, 0.52)),
    "tarnished": (tarnished, 30, (0.84, 0.84, 0.5, 0.5)),
}


def fit(solids, v, frame_box):
    """Zoom and centre that fit the solids' silhouette to the box, so every icon has the same margins."""
    size, z0 = 512, 0.2
    fid = render(solids, v, size, zoom=z0, center=(0, 0))[0]
    ys, xs = np.nonzero(fid >= 0)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    fw, fh, cx, cy = frame_box
    z = z0 * min(fw * size / (x1 - x0), fh * size / (y1 - y0))
    vx = ((x0 + x1) / 2 - size / 2) / (z0 * size)
    vy = ((y0 + y1) / 2 - size / 2) / (z0 * size)
    return {"zoom": z, "center": (cx - 0.5 - vx * z, cy - 0.5 - vy * z)}


class Icon:
    def __init__(self, name, N, k=0):
        build, pitch, frame_box = ICONS[name]
        self.name, self.N = name, N
        self.solids, self.focus = build(k) if name in ("furnace", "crucible") else build()
        self.view = view(pitch)
        # The fit uses frame 0, so a flickering melt never moves the icon.
        self.kw = fit((build(0) if name in ("furnace", "crucible") else build())[0], self.view, frame_box)

    def base(self):
        return pixel_art(self.solids, self.view, self.N, freq=FREQ[self.N], stripes=self.N >= 24, **self.kw)

    def focus_mask(self):
        return pixel_art(self.focus, self.view, self.N, freq=FREQ[self.N], edge_hi=False, **self.kw)[..., 3] > 0

    def glint_at(self):
        return glint_point(self.focus, self.view, self.N, freq=FREQ[self.N], **self.kw)


# ---------- overlays ----------
def glint(img, pos, size):
    out = img.copy()
    cy, cx = pos
    if not size:
        return out
    out[cy, cx] = WHITE_HOT
    for d in range(1, size + 1):
        for dy, dx in ((0, d), (0, -d), (d, 0), (-d, 0)):
            y, x = cy + dy, cx + dx
            if 0 <= y < img.shape[0] and 0 <= x < img.shape[1]:
                out[y, x] = WHITE_HOT if d < size else GLINT_EDGE
    return out


def sparks(N, seed):
    """Sixteen sparks fanning sideways and falling, as off a struck flint rather than a fuse."""
    rng = np.random.default_rng(seed)
    k = N / 48
    return [{"ang": np.radians(rng.uniform(-38, 34)), "v": rng.uniform(1.8, 3.4) * k, "delay": int(rng.integers(0, 3)),
             "life": int(rng.integers(6, 11)), "g": 0.16 * k} for _ in range(16)]


def spark_frame(img, origin, t, parts, flash=True):
    out = img.copy()
    N = img.shape[0]
    oy, ox = origin

    def put(y, x, col):
        y, x = int(round(y)), int(round(x))
        if 0 <= y < N and 0 <= x < N:
            out[y, x] = (*col, 255)

    if flash and t <= 1:
        for d in range(-(2 - t), 3 - t):
            put(oy + d, ox, SPARK[0])
            put(oy, ox + d, SPARK[0])
    for q in parts:
        tt = t - q["delay"]
        if tt < 0 or tt > q["life"]:
            continue

        def pos(s, q=q):
            return oy + np.sin(q["ang"]) * q["v"] * s + 0.5 * q["g"] * s * s, ox + np.cos(q["ang"]) * q["v"] * s

        age = tt / q["life"]
        head, tail = pos(tt), pos(max(tt - 2.4, 0))
        for i in range(7):
            f = i / 6
            colour = SPARK[min(len(SPARK) - 1, int(age * 4) + (0 if f > 0.75 else 2))]
            put(tail[0] + (head[0] - tail[0]) * f, tail[1] + (head[1] - tail[1]) * f, colour)
    return out


def side_of(mask):
    """Where sparks leave the crystal: its right-hand edge, near the middle."""
    ys, xs = np.nonzero(mask)
    cy = (ys.min() + ys.max()) / 2
    j = np.argmax(xs - 0.25 * np.abs(ys - cy))
    return int(ys[j]), int(xs[j]) + 1


def interior(m):
    e = m.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        e &= np.roll(np.roll(m, dy, 0), dx, 1)
    return e


def bubbles(img, m, rng, n):
    out = img.copy()
    ys, xs = np.nonzero(interior(m))
    for j in rng.choice(len(ys), size=min(n, len(ys)), replace=False):
        out[ys[j], xs[j]] = (*GLOW[8], 255)
    return out


def embers(img, row, x0, x1, t, seed=5, n=5):
    out = img.copy()
    N = img.shape[0]
    rng = np.random.default_rng(seed)
    for i in range(n):
        x, phase, speed = rng.uniform(x0, x1), rng.uniform(0, 1), rng.uniform(0.35, 0.6)
        tt = (t / 14 + phase) % 1.0
        y = row - tt * 14 * speed * (N / 48) * 1.6
        colour = GLOW[7] if tt < 0.3 else GLOW[5] if tt < 0.65 else GLOW[3]
        yi, xi = int(round(y)), int(round(x + np.sin(tt * 6 + i) * 1.2))
        if 0 <= yi < N and 0 <= xi < N and out[yi, xi, 3] == 0 and tt < 0.9:
            out[yi, xi] = (*colour, 255)
    return out


def despike(rgba):
    """For 16 px: drop one-pixel spurs of fill, which make bumps in the outline, then outline again."""
    fill = (rgba[..., 3] > 0) & np.any(rgba[..., :3] != INK, -1)
    while True:
        n4 = sum(np.roll(np.roll(fill, dy, 0), dx, 1).astype(int) for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        spur = fill & (n4 <= 1)
        if not spur.any():
            break
        fill &= ~spur
    return outline(rgba[..., :3].copy(), fill)


# ---------- the assay balance, drawn in 2D with rendered crystal and bead ----------
_sprites: dict[int, tuple[np.ndarray, np.ndarray]] = {}


def balance_sprites(N):
    if N not in _sprites:
        cs, bs = max(6, round(N * 0.24)), max(3, round(N * 0.11))
        c, b, v = [crystal()], [Solid(BEAD, **smooth(GOLD))], view(30)
        _sprites[N] = (pixel_art(c, v, cs, freq=2.5, stripes=cs >= 12, **fit(c, v, (0.8, 0.8, 0.5, 0.5))),
                       pixel_art(b, v, bs, freq=2.5, stripes=False, **fit(b, v, (0.7, 0.7, 0.5, 0.5))))
    return _sprites[N]


def paste(dst, src, cy, cx):
    h, w = src.shape[:2]
    y0, x0 = int(round(cy - h / 2)), int(round(cx - w / 2))
    for y in range(h):
        for x in range(w):
            if src[y, x, 3] and 0 <= y0 + y < dst.shape[0] and 0 <= x0 + x < dst.shape[1]:
                dst[y0 + y, x0 + x] = src[y, x]


def balance(N, theta):
    """The balance with its beam at `theta` degrees, right end down: pyrite on the left pan, a gold prill on the right."""
    S = N * 8
    layers = {k: Image.new("L", (S, S)) for k in ("frame", "beam", "pans", "string")}
    draw = {k: ImageDraw.Draw(v) for k, v in layers.items()}
    u = S / 48.0
    cx, pivot = 24 * u, 13 * u
    draw["frame"].polygon([(14 * u, 44 * u), (34 * u, 44 * u), (31 * u, 40.5 * u), (17 * u, 40.5 * u)], fill=255)
    draw["frame"].rectangle([22.8 * u, 13 * u, 25.2 * u, 41 * u], fill=255)
    draw["frame"].ellipse([21.5 * u, 10.5 * u, 26.5 * u, 15.5 * u], fill=255)
    th, arm = np.radians(theta), 14 * u
    ends = [(cx - arm * np.cos(th), pivot - arm * np.sin(th)), (cx + arm * np.cos(th), pivot + arm * np.sin(th))]
    draw["beam"].line([ends[0], ends[1]], fill=255, width=int(2.4 * u))
    pans = []
    for ex, ey in ends:
        py = ey + 12 * u
        draw["string"].line([(ex, ey), (ex - 4.5 * u, py)], fill=255, width=int(0.9 * u))
        draw["string"].line([(ex, ey), (ex + 4.5 * u, py)], fill=255, width=int(0.9 * u))
        draw["pans"].chord([ex - 6 * u, py - 2.5 * u, ex + 6 * u, py + 2.5 * u], 0, 180, fill=255)
        pans.append((ex / 8, py / 8))

    def down(im, threshold=110):
        return np.asarray(im.resize((N, N), Image.BOX)) > threshold

    fm, bm, pm, sm = down(layers["frame"]), down(layers["beam"]), down(layers["pans"]), down(layers["string"], 70)
    rgb = np.zeros((N, N, 3), np.uint8)
    rgb[sm] = BRASS[3]
    for m in (fm, bm, pm):
        rgb[m] = shade_mask(m, BRASS, 5, 7, 3)[m]
    img = outline(rgb, fm | bm | pm | sm)
    cspr, bspr = balance_sprites(N)
    (lx, ly), (rx, ry) = pans
    paste(img, cspr, ly - cspr.shape[0] / 2 + 0.5, lx)
    paste(img, bspr, ry - bspr.shape[0] / 2 + 0.5, rx)
    return img


def balance16():
    """The balance placed by hand at 16 px, where the drawn one loses its beam."""
    B, G = BRASS, GOLD
    px = {(7, 2): B[7], (8, 2): B[7], (7, 3): B[5], (8, 3): B[5]}
    px.update({(x, 3): B[7] for x in range(1, 5)})  # beam: left end high
    px.update({(x, 4): B[6] for x in range(5, 11)})
    px.update({(x, 5): B[5] for x in range(11, 15)})  # right end low, the gold side
    for y in range(5, 12):
        px[(7, y)], px[(8, y)] = B[7], B[3]
    px.update({(x, 12): B[6] for x in range(6, 10)})
    px.update({(x, 13): B[4] for x in range(4, 12)})
    px.update({(2, 4): B[3], (2, 5): B[7], (3, 5): B[6], (2, 6): B[4], (3, 6): B[2]})  # string, pyrite crystal
    px.update({(x, 7): B[6] for x in range(1, 5)})
    px.update({(2, 8): B[3], (3, 8): B[3], (13, 6): B[3], (13, 7): B[3], (12, 8): G[7], (13, 8): G[5]})  # gold prill
    px.update({(x, 9): B[6] for x in range(11, 15)})
    px.update({(12, 10): B[3], (13, 10): B[3]})
    rgb, m = np.zeros((16, 16, 3), np.uint8), np.zeros((16, 16), bool)
    for (x, y), c in px.items():
        rgb[y, x], m[y, x] = c, True
    return outline(rgb, m)


BALANCE_REST = 13.0


# ---------- stills and animations ----------
def still(name, N):
    if name == "balance":
        return balance16() if N == 16 else balance(N, BALANCE_REST)
    icon = Icon(name, N)
    base = icon.base()
    if N == 16:
        base = despike(base)
    if name in ("working", "anvil"):
        parts, origin = sparks(N, 3 if name == "working" else 11), side_of(icon.focus_mask())
        for t in (2, 4, 6) if N >= 24 else (3,):
            base = spark_frame(base, origin, t, parts, flash=False)
        return base
    if name == "crucible":
        return bubbles(base, interior(icon.focus_mask()), np.random.default_rng(4), 1) if N >= 24 else base
    if name == "furnace":
        return base
    size = {16: 0, 24: 1, 32: 1, 48: 2}[N]
    if size == 0:
        out = base.copy()
        out[icon.glint_at()] = WHITE_HOT
        return out
    return glint(base, icon.glint_at(), size)


BLICK = [(255, 251, 230), (232, 246, 255), (185, 232, 240), (242, 184, 230), (255, 240, 160)]


def frames(name, N=48):
    """(frames, milliseconds per frame), or None for an icon that stays still."""
    if name == "tarnished":
        return None  # fool's gold, set aside: it never sparkles
    if name == "balance":
        swing = [BALANCE_REST * (1 - np.exp(-t / 2.2) * np.cos(t * 1.25)) for t in range(14)]
        return [balance(N, 0)] * 4 + [balance(N, a) for a in swing] + [balance(N, BALANCE_REST)] * 12, 90
    if name in ("working", "anvil"):
        icon = Icon(name, N)
        base, origin, parts = icon.base(), side_of(icon.focus_mask()), sparks(N, 3 if name == "working" else 11)
        return [base] * 18 + [spark_frame(base, origin, t, parts) for t in range(12)], 80
    if name in ("crucible", "furnace"):
        first = Icon(name, N)
        m = pixel_art(first.focus, first.view, N, freq=3.0, edge_hi=False, **first.kw)[..., 3] > 0
        ys, xs = np.nonzero(m)
        rng, out = np.random.default_rng(1), []
        for t in range(16):
            f = Icon(name, N, k=t).base()
            if name == "crucible":
                f = bubbles(f, m, rng, 1 + (t % 3 == 0))
                out.append(embers(f, ys.min() - 1, xs.min() + 2, xs.max() - 2, t))
            else:
                out.append(embers(f, ys.min() - 1, xs.min() + 1, xs.max() - 1, t, seed=9, n=3))
        return out, 100 if name == "crucible" else 110
    icon = Icon(name, N)
    base, at = icon.base(), icon.glint_at()
    if name == "cupel":
        bead = interior(icon.focus_mask())
        flash = []
        for c in BLICK:  # the blick: the bead's play of colour as the last lead burns off
            f = base.copy()
            f[bead, :3] = (f[bead, :3] * 0.35 + np.array(c, float) * 0.65).astype(np.uint8)
            flash.append(f)
        return [base] * 14 + flash + [glint(base, at, s) for s in (1, 2, 3, 2, 1)] + [base] * 4, 110
    return [glint(base, at, s) for s in [0] * 11 + [1, 2, 3, 2, 1]], 110
