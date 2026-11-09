"""A small z-buffer renderer for convex solids, drawn as pixel art.

Every icon is built from convex solids (a pyritohedron, boxes, many-sided frustums), rendered at 16 samples per
pixel, then reduced to one face per pixel and shaded from a nine-step ramp. Crystal faces carry pyrite's
striations, which run at right angles on neighbouring faces, as they do on the mineral.

Screen axes: x right, y down, z into the screen, camera at -z. Up in an object's own coordinates is -y.
"""

import itertools

import numpy as np
from palette import BRASS, INK, outline
from PIL import Image, ImageDraw

LIGHT = (-0.55, -0.7, -0.6)  # toward the light: upper left, in front


def rot(yaw: float, pitch: float, roll: float = 0.0) -> np.ndarray:
    y, p, r = np.radians([yaw, pitch, roll])
    ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    rx = np.array([[1, 0, 0], [0, np.cos(p), -np.sin(p)], [0, np.sin(p), np.cos(p)]])
    rz = np.array([[np.cos(r), -np.sin(r), 0], [np.sin(r), np.cos(r), 0], [0, 0, 1]])
    return rx @ ry @ rz


def hull_faces(v: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """Faces of a convex polytope by brute force: ordered vertex indices and the outward normal of each."""
    faces, seen = [], set()
    c = v.mean(0)
    for i, j, k in itertools.combinations(range(len(v)), 3):
        n = np.cross(v[j] - v[i], v[k] - v[i])
        if np.linalg.norm(n) < 1e-9:
            continue
        n /= np.linalg.norm(n)
        d = v @ n - v[i] @ n
        if (d > 1e-7).any() and (d < -1e-7).any():
            continue
        if (v[i] - c) @ n < 0:
            n = -n
        on = tuple(sorted(np.nonzero(np.abs(d) < 1e-7)[0]))
        if on in seen:
            continue
        seen.add(on)
        pts = v[list(on)]
        fc = pts.mean(0)
        u = pts[0] - fc
        u /= np.linalg.norm(u)
        w = np.cross(n, u)
        ang = np.arctan2((pts - fc) @ w, (pts - fc) @ u)
        faces.append((np.array(on)[np.argsort(ang)], n))
    return faces


CUBE = np.array(list(itertools.product([-1, 1], repeat=3)), float)


def pyritohedron(h: float = 0.5) -> np.ndarray:
    """Pyrite's twelve-faced crystal: a cube with a roof on each face, the roofs' ridges turned 90 degrees apart."""
    a, b = 1 + h, 1 - h * h
    v = list(CUBE)
    for s1 in (-1, 1):
        for s2 in (-1, 1):
            v += [(0, s1 * a, s2 * b), (s1 * a, s2 * b, 0), (s2 * b, 0, s1 * a)]
    return np.array(v, float)


def sphere(n: int = 48) -> np.ndarray:
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = np.pi * (1 + 5 ** 0.5) * i
    return np.c_[np.cos(th) * np.sin(phi), np.cos(phi), np.sin(th) * np.sin(phi)]


def box(x0, x1, y0, y1, z0, z1) -> np.ndarray:
    return np.array([(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], float)


def frustum(r_bottom, y_bottom, r_top, y_top, n=20) -> np.ndarray:
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.array([(r_bottom * np.cos(t), y_bottom, r_bottom * np.sin(t)) for t in a] +
                    [(r_top * np.cos(t), y_top, r_top * np.sin(t)) for t in a])


class Solid:
    """A convex solid placed in the scene. `ramp` None uses the picture's ramp; `stripes` marks crystal faces."""

    def __init__(self, v, R=None, t=(0, 0, 0), scale=1.0, ramp=None, stripes=True):
        self.v, self.R, self.t, self.s = v, np.eye(3) if R is None else R, np.array(t, float), scale
        self.ramp, self.stripes = ramp, stripes
        self.faces = hull_faces(v)


def render(solids, view, size, zoom=0.36, center=(0, 0)):
    """Face id per sample, a tone per face and each sample's striation coordinate, plus the solid owning each face."""
    L = np.array(LIGHT, float)
    L /= np.linalg.norm(L)
    H = L + np.array([0, 0, -1])
    H /= np.linalg.norm(H)
    fid = np.full((size, size), -1, int)
    depth = np.full((size, size), np.inf)
    stripe = np.zeros((size, size))
    tones: list[float] = []
    owner: list[int] = []
    ys, xs = np.mgrid[0:size, 0:size] + 0.5
    vx = (xs - size / 2 - center[0] * size) / (zoom * size)
    vy = (ys - size / 2 - center[1] * size) / (zoom * size)
    k = 0
    for si, so in enumerate(solids):
        owner += [si] * len(so.faces)
        M = view @ so.R
        vw = (so.v * so.s) @ M.T + view @ so.t
        P = np.c_[vw[:, 0] * zoom * size + size / 2 + center[0] * size, vw[:, 1] * zoom * size + size / 2 + center[1] * size]
        for idx, nloc in so.faces:
            n = M @ nloc
            if n[2] >= 0:  # facing away
                tones.append(0.0)
                k += 1
                continue
            m = Image.new("1", (size, size), 0)
            ImageDraw.Draw(m).polygon([tuple(p) for p in P[idx]], fill=1)
            mask = np.asarray(m)
            z = (n @ vw[idx[0]] - n[0] * vx - n[1] * vy) / n[2]
            upd = mask & (z < depth)
            depth[upd] = z[upd]
            fid[upd] = k
            # Striations run along the axis after the face's own: X faces along Y, Y along Z, Z along X.
            var = (int(np.argmax(np.abs(nloc))) + 2) % 3
            ploc = ((np.stack([vx, vy, z], -1) - view @ so.t) @ M) / so.s
            stripe[upd] = ploc[..., var][upd]
            hl = 0.5 + 0.5 * (n @ L)  # half-Lambert keeps the shadow side readable
            tones.append(0.1 + 0.85 * hl * hl + 0.35 * max(0.0, n @ H) ** 24)
            k += 1
    return fid, np.array(tones), stripe, np.array(owner, int)


def pixel_art(solids, view, N, freq=3.0, stripes=True, edge_hi=True, ss=16, **kw):
    """Render to an N x N RGBA image: one face per pixel, striations, lit creases and an ink outline."""
    fid, tones, stripe, owner = render(solids, view, N * ss, **kw)
    f = fid.reshape(N, ss, N, ss).transpose(0, 2, 1, 3).reshape(N, N, -1)
    cov = (f >= 0).mean(-1)
    cell = np.full((N, N), -1, int)
    for y in range(N):
        for x in range(N):
            v = f[y, x][f[y, x] >= 0]
            if cov[y, x] >= 0.5 and len(v):
                cell[y, x] = np.bincount(v).argmax()
    st = stripe.reshape(N, ss, N, ss).mean((1, 3))
    n_ramp = len(BRASS)
    tidx = np.clip(np.round(tones * (n_ramp - 2)), 1, n_ramp - 2).astype(int)
    mask = cell >= 0
    safe = np.clip(cell, 0, None)
    idx = np.where(mask, tidx[safe], 0)
    sid = np.where(mask, owner[safe], -1)
    striped = np.array([so.stripes for so in solids])
    if stripes:
        idx[(np.floor(st * freq) % 2 == 1) & mask & striped[np.clip(sid, 0, None)]] -= 1
    if edge_hi:
        # Brighten a lighter face where it meets a darker one. Round and flat objects only get it on a real crease.
        need = np.where(striped[owner[safe]], 1, 2)
        own = np.where(mask, tidx[safe], -1)
        for dy, dx in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            nb = np.roll(np.roll(cell, dy, 0), dx, 1)
            nbt = np.where(nb >= 0, tidx[np.clip(nb, 0, None)], 99)
            e = mask & (nb >= 0) & (nb != cell) & (own - nbt >= need)
            idx[e] = np.minimum(own[e] + 2, n_ramp - 1)
    idx = np.clip(idx, 0, n_ramp - 1)
    rgb = BRASS[idx]
    for i, so in enumerate(solids):
        if so.ramp is not None:
            sel = sid == i
            rgb[sel] = so.ramp[idx[sel]]
    return outline(rgb, mask)


def glint_point(solids, view, N, freq=3.0, **kw):
    """Where a glint sits: the brightest pixel nearest the top left, nudged inward at larger sizes."""
    art = pixel_art(solids, view, N, freq=freq, **kw)
    # One solid, one ramp: the brightest colour inside the outline is the brightest ramp step.
    lum = art[..., :3].astype(int).sum(-1)
    body = (art[..., 3] > 0) & np.any(art[..., :3] != INK, -1)
    ys, xs = np.nonzero(body & (lum == lum[body].max()))
    j = np.argmin(ys * 2 + xs)
    off = 1 if N >= 24 else 0
    return int(ys[j]) + off, int(xs[j]) + off
