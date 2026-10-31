"""Shared luma SSIM comparison; defaults match the stage suite."""
from pathlib import Path

import numpy as np
from PIL import Image


def ssim(a: Path, b: Path, tile: tuple[int, int] = (480, 270)) -> float:
    """Mean SSIM over 8×8 windows on luma — enough to tell a changed frame
    from GPU noise."""
    x = np.asarray(Image.open(a).convert("L").resize(tile), dtype=np.float64)
    y = np.asarray(Image.open(b).convert("L").resize(tile), dtype=np.float64)

    def box(z, k=8):
        c = np.pad(z, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)
    mx, my = box(x), box(y)
    vx, vy, cxy = box(x * x) - mx * mx, box(y * y) - my * my, box(x * y) - mx * my
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    s = ((2 * mx * my + c1) * (2 * cxy + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))
    return float(s.mean())


