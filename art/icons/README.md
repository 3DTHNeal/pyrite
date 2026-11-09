# Pyrite's icons

Everything here draws the logo, the favicon, the dashboard's wordmark and its stage icons, each at 24 px for a stage's name and 48 px for the job panel and empty views. None of it was traced or adapted from a photograph: each icon is rendered from geometry.

```sh
pip install -r art/icons/requirements.txt
python art/icons/build.py
```

That rewrites `tools/pyrite/static/icons/` and `docs/images/`. Pyrite needs neither Pillow nor numpy to run. Only the PNGs ship.

## How they're made

- `render.py` is a small z-buffer renderer for convex solids. It renders at 16 samples a pixel, keeps the face that covers most of each pixel, shades it from a nine-step ramp, brightens creases where a lit face meets a darker one, and adds a 1-pixel ink outline.
- The crystal is a pyritohedron, pyrite's twelve-faced habit. Its faces carry pyrite's striations, which run at right angles on neighbouring faces, as they do on the mineral.
- `scenes.py` builds each icon. They share one camera family (yaw 30 degrees), one light from the upper left, one crystal in one pose, and the same margins: each scene is fitted to its box before it's drawn. At 16 px, one-pixel spurs are trimmed so the outline stays smooth, and the balance is placed by hand.
- `palette.py` holds the ramps. Pyrite is pale brass and real gold is warmer and more orange, so the two read apart wherever they meet. The dashboard's colours in `style.css` come from the same ramps: brass for controls, the pan's water-green for information and gold's orange for warnings.

## The animations

Each animation is one PNG strip of frames, stepped through by CSS `steps()` in `style.css`. The mark's idle strip glints once in 16 frames. Its working strip throws a burst of sparks over 30. Where the frame count changes, change `--frames` in `style.css` to match. A test checks the two agree.
