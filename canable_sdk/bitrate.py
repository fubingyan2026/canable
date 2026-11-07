"""CAN nominal and data-phase bit timing tables.

CAN clock = 160 MHz.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class TimingLimits:
    seg1_min: int = 1
    seg1_max: int = 256
    seg2_min: int = 1
    seg2_max: int = 128
    sjw_max: int = 128
    brp_min: int = 1
    brp_max: int = 512
    brp_inc: int = 1

    def accepts(self, timing):
        brp, seg1, seg2, sjw = timing
        return (self.brp_min <= brp <= self.brp_max
                and (brp - self.brp_min) % self.brp_inc == 0
                and self.seg1_min <= seg1 <= self.seg1_max
                and self.seg2_min <= seg2 <= self.seg2_max
                and 1 <= sjw <= min(seg1, seg2, self.sjw_max))


# Conservative data-phase fallback for firmware lacking extended capabilities.
DATA_LIMITS = TimingLimits(seg1_max=15, seg2_max=15, sjw_max=15, brp_max=32)


@lru_cache(maxsize=256)
def calculate_timing(bitrate: int, clock: int, limits: TimingLimits,
                     sample_point: float):
    """Search total quanta and adjacent prescalers, rather than all triples."""
    best_key = None
    best = None
    for total in range(1 + limits.seg1_min + limits.seg2_min,
                       2 + limits.seg1_max + limits.seg2_max):
        lo = max(limits.seg1_min, total - 1 - limits.seg2_max)
        hi = min(limits.seg1_max, total - 1 - limits.seg2_min)
        target_seg1 = sample_point * total - 1
        seg1 = min(hi, max(lo, int(round(target_seg1))))
        seg2 = total - 1 - seg1
        ideal = clock / (total * bitrate)
        grid = math.floor((ideal - limits.brp_min) / limits.brp_inc)
        for step in (grid, grid + 1):
            brp = limits.brp_min + step * limits.brp_inc
            brp = min(limits.brp_max - (limits.brp_max - limits.brp_min) % limits.brp_inc,
                      max(limits.brp_min, brp))
            rate_error = abs(clock / (brp * total) - bitrate) / bitrate
            if rate_error > 0.01:
                continue
            key = (rate_error, abs((1 + seg1) / total - sample_point), -total)
            if best_key is None or key < best_key:
                best_key = key
                best = (brp, seg1, seg2, min(seg1, seg2, limits.sjw_max))
    if best is None:
        raise ValueError(f"cannot compute bit timing for {bitrate} bps within 1%")
    return best

NOMINAL_BITTIMING = {
    10_000:    (80,  174, 25, 25),
    20_000:    (40,  174, 25, 25),
    50_000:    (16,  174, 25, 25),
    83_333:    (10,  167, 24, 24),
    100_000:   (8,   174, 25, 25),
    125_000:   (8,   139, 20, 20),
    250_000:   (4,   139, 20, 20),
    500_000:   (2,   139, 20, 20),
    800_000:   (1,   174, 25, 25),
    1_000_000: (1,   139, 20, 20),
}

DATA_BITTIMING = {
    # Seg1=5, Seg2=2 → 75% sample point. Device capabilities supply actual limits.
    500_000:   (20, 11, 4, 2),  # 160MHz / 20 / 16 = 500k, 75% (brp 不得超过 32: 数据相位 DBRP 只有 5 位)
    1_000_000: (20, 5, 2, 2),   # 160MHz / 20 / 8 = 1M
    2_000_000: (10, 5, 2, 2),   # 160MHz / 10 / 8 = 2M
    4_000_000: (5,  5, 2, 2),   # 160MHz / 5  / 8 = 4M
    5_000_000: (4,  5, 2, 2),   # 160MHz / 4  / 8 = 5M
    8_000_000: (5,  1, 2, 1),   # 160MHz / 5  / 4 = 8M, 50% (firmware requires 50%)
}
