"""Offline proxy quality heuristics. Scores are hints; media is never changed."""
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from . import ffutil

# All decision thresholds live here. Luma is full-range 0..255 at 160x90;
# shake is pixels per sampled pair (8 fps), audio is linear full-scale RMS.
THRESHOLDS = {
    'blur_min': 35.0, 'shake_max': 4.0,
    'black_luma': 8, 'white_luma': 247, 'exposure_max': .85,
    'audio_min': .003, 'audio_max': .7, 'wind_max': .75,
    'wind_hz': 200, 'hash_distance': 8, 'duration_tolerance': .1,
    'duplicate_luma_max': 20,
    # Mean-luma exposure catches frames that are dim overall but not clipped.
    'dark_mean_max': 40, 'bright_mean_min': 225,
    # Laplacian variance depends on content, so also compare within the shoot.
    'soft_vs_median': .2, 'soft_min_clips': 3,
}
SIZE = (160, 90)
SAMPLE_FPS = 8
AUDIO_RATE = 8000


def _shift(a, b):
    """Phase correlation, with wrapped offsets in the downscaled frame."""
    a, b = a.astype(float), b.astype(float)
    cross = np.fft.fft2(a - a.mean()) * np.conj(np.fft.fft2(b - b.mean()))
    cross /= np.maximum(np.abs(cross), 1e-12)
    peak = np.unravel_index(np.argmax(np.fft.ifft2(cross).real), a.shape)
    return float(np.linalg.norm([p if p <= n // 2 else p - n
                                 for p, n in zip(peak, a.shape)]))


def _hash(frame):
    """64-bit perceptual hash of low-frequency DCT coefficients (without DC)."""
    small = np.asarray(Image.fromarray(frame).resize((32, 32), Image.Resampling.LANCZOS),
                       dtype=float)
    basis = np.cos(np.pi / 32 * (np.arange(32) + .5) * np.arange(8)[:, None])
    values = (basis @ small @ basis.T).ravel()[1:]
    bits = values > np.median(values)
    return format(sum(int(bit) << i for i, bit in enumerate(bits)), '016x')


def _audio_scores(samples):
    if not len(samples):
        return None, None
    samples = samples.astype(float)
    rms = float(np.sqrt(np.mean(samples ** 2)))
    # Short windows keep memory bounded and measure low-frequency energy
    # throughout the clip, rather than depending on its total duration.
    power = np.zeros(513)
    for start in range(0, len(samples), 1024):
        chunk = samples[start:start + 1024]
        chunk = (chunk - chunk.mean()) * np.hanning(len(chunk))
        power += np.abs(np.fft.rfft(chunk, n=1024)) ** 2
    frequencies = np.fft.rfftfreq(1024, 1 / AUDIO_RATE)
    wind = float(power[(frequencies > 0) & (frequencies <= THRESHOLDS['wind_hz'])].sum()
                 / max(float(power.sum()), 1e-20))
    return rms, wind


def score_frames(frames, samples=None):
    """Three distributed frames for blur/exposure, adjacent pairs for shake."""
    if not len(frames):
        raise ValueError('No proxy frames in clip')
    selected = frames[[min(len(frames) - 1, int(len(frames) * f)) for f in (.1, .5, .9)]]
    variances = []
    for frame in selected.astype(float):
        laplacian = (frame[:-2, 1:-1] + frame[2:, 1:-1] + frame[1:-1, :-2]
                     + frame[1:-1, 2:] - 4 * frame[1:-1, 1:-1])
        variances.append(float(laplacian.var()))
    blur = float(np.mean(variances))
    shake = float(np.mean([_shift(a, b) for a, b in zip(frames, frames[1:])])) if len(frames) > 1 else 0.
    dark = float(np.mean(selected <= THRESHOLDS['black_luma']))
    bright = float(np.mean(selected >= THRESHOLDS['white_luma']))
    rms, wind = _audio_scores(samples) if samples is not None else (None, None)
    reasons = []
    for failed, reason in (
        (blur < THRESHOLDS['blur_min'], 'blur'),
        (shake > THRESHOLDS['shake_max'], 'shake'),
        (dark > THRESHOLDS['exposure_max']
         or selected.mean() < THRESHOLDS['dark_mean_max'], 'underexposed'),
        (bright > THRESHOLDS['exposure_max']
         or selected.mean() > THRESHOLDS['bright_mean_min'], 'overexposed'),
        (rms is not None and rms < THRESHOLDS['audio_min'], 'quiet_audio'),
        (rms is not None and rms > THRESHOLDS['audio_max'], 'loud_audio'),
        (rms is not None and rms >= THRESHOLDS['audio_min']
         and wind > THRESHOLDS['wind_max'], 'wind'),
    ):
        if failed:
            reasons.append(reason)
    return dict(blur=blur, shake=shake, dark_fraction=dark, bright_fraction=bright,
                audio_rms=rms, wind_fraction=wind, usable=not reasons, reasons=reasons,
                phash=_hash(selected[1]), mean_luma=float(selected[1].mean()))


def analyze_clip(proxy: Path, start: float, end: float, has_audio: bool):
    """Decode only the clip span, never original camera media or thumbnails."""
    if not 0 <= start < end:
        raise ValueError('Require 0 <= clip in < out')
    with TemporaryDirectory(prefix='corkbored-quality-') as directory:
        video = Path(directory) / 'frames.raw'
        args = ['-ss', str(start), '-i', str(proxy), '-t', str(end - start),
                '-map', '0:v:0', '-an', '-vf', f'fps={SAMPLE_FPS}:round=up,scale=160:90',
                '-pix_fmt', 'gray', '-f', 'rawvideo', str(video)]
        audio = Path(directory) / 'audio.raw'
        if has_audio:
            args += ['-t', str(end - start), '-map', '0:a:0', '-vn',
                     '-ac', '1', '-ar', str(AUDIO_RATE), '-f', 'f32le', str(audio)]
        ffutil.run(args, threads=1)
        frames = np.fromfile(video, dtype=np.uint8).reshape(-1, SIZE[1], SIZE[0])
        samples = np.fromfile(audio, dtype='<f4') if has_audio else None
        return score_frames(frames, samples)


def group_duplicates(clips):
    """Connected near-duplicate groups; deterministic IDs and best-take ties."""
    parents = list(range(len(clips)))

    def root(i):
        while parents[i] != i:
            i = parents[i]
        return i

    for i, a in enumerate(clips):
        a.duplicate_group = a.best_take = ''
        for j, b in enumerate(clips[:i]):
            da, db = a.out_s - a.in_s, b.out_s - b.in_s
            if (not a.quality.get('phash') or not b.quality.get('phash')
                    or min(da, db) <= 0):
                continue
            distance = (int(a.quality['phash'], 16) ^ int(b.quality['phash'], 16)).bit_count()
            if (abs(da - db) / max(da, db) <= THRESHOLDS['duration_tolerance']
                    and abs(a.quality['mean_luma'] - b.quality['mean_luma'])
                    <= THRESHOLDS['duplicate_luma_max']
                    and distance <= THRESHOLDS['hash_distance']):
                parents[root(i)] = root(j)
    groups = {}
    for i, clip in enumerate(clips):
        groups.setdefault(root(i), []).append(clip)
    for members in groups.values():
        if len(members) < 2:
            continue
        best = min(members, key=lambda c: (
            THRESHOLDS['blur_min'] / max(c.quality['blur'], 1e-6)
            + c.quality['shake'] / THRESHOLDS['shake_max'], c.id))
        group_id = min(c.id for c in members)
        for clip in members:
            clip.duplicate_group, clip.best_take = group_id, best.id


def flag_soft(clips):
    """Flag clips far softer than the shoot's median. Dim clips are left to
    the exposure flag, since low light alone lowers Laplacian variance."""
    scored = [c for c in clips if c.quality.get('blur') is not None]
    if len(scored) < THRESHOLDS['soft_min_clips']:
        return
    cutoff = float(np.median([c.quality['blur'] for c in scored])) * THRESHOLDS['soft_vs_median']
    for clip in scored:
        q = clip.quality
        if (q['blur'] < cutoff and 'blur' not in q['reasons']
                and 'underexposed' not in q['reasons']):
            q['reasons'] = q['reasons'] + ['blur']
            q['usable'] = False
