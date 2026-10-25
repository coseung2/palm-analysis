"""Local palm-line tracer: landmark-normalized palm, ridge evidence, per-line corridor DP.

Every line is traced only where the photo shows a continuous crease inside an anatomical
corridor; weak or absent creases come back as not visible instead of a template drawing.
The result is visual evidence for the experience, not a validated palmistry measurement.
"""
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

SIZE = 512
# Similarity targets for landmarks in the canonical palm (thumb on the right, fingers up).
CANON = {0: (0.50, 0.92), 5: (0.76, 0.28), 9: (0.56, 0.25), 13: (0.38, 0.27), 17: (0.22, 0.32)}

# Corridor centreline in palm (u, v): u 0 at pinky MCP .. 1 at index MCP, v 0 on the MCP line
# .. 1 at the wrist. hw is the corridor half-width in palm widths; tau is the evidence level
# a crease pixel must exceed to lengthen a line.
LINES = {
    'head':  dict(c=[(1.08, 0.16), (0.75, 0.20), (0.40, 0.26), (0.05, 0.31), (-0.15, 0.34)], hw=0.23, tau=0.30, classes=0),
    'heart': dict(c=[(-0.15, 0.08), (0.20, 0.07), (0.50, 0.03), (0.72, -0.04), (0.85, -0.10)], hw=0.13, tau=0.30, classes=0),
    'life':  dict(c=[(1.05, 0.22), (0.85, 0.36), (0.71, 0.55), (0.63, 0.78), (0.62, 1.05)], hw=0.19, tau=0.30),
    'fate':  dict(c=[(0.50, 1.02), (0.50, 0.60), (0.50, 0.25), (0.50, 0.00)], hw=0.13, tau=0.38, learned=.35),
    'sun':   dict(c=[(0.30, 0.80), (0.31, 0.45), (0.30, 0.10), (0.30, -0.02)], hw=0.08, tau=0.42, learned=.35),
}
ORDER = ('head', 'heart', 'life', 'fate', 'sun')
MIN_LENGTH = {'head': .30, 'heart': .30, 'life': .30, 'fate': .30, 'sun': .25}
MAX_STEP, LAMBDA, MU = 1, .08, .25
# Raw Sato p99.5 on the shading-flattened palm; phone photos measured .03-.05, noise ~.007.
ABSOLUTE_CONTRAST = .025
# Evidence level that may continue an already accepted line towards its true ends.
EXTEND_TAU = .18
DEBUG_JOINT = False
JOINT_MARGIN = 1.1


@dataclass
class TracedLine:
    name: str
    visible: bool
    length: float = 0.0
    support: float = 0.0
    canonical: list = field(default_factory=list)   # [(x, y)] in the 512 canonical palm
    points: list = field(default_factory=list)      # [(x, y)] normalized to the input photo


@dataclass
class PalmTrace:
    mirrored: bool
    lines: dict
    minor: dict
    canonical_image: np.ndarray
    evidence: np.ndarray
    matrix: np.ndarray


def _hand_landmarks(image: Image.Image):
    import mediapipe as mp

    arr = np.asarray(image.convert('RGB'))
    with mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=2, model_complexity=1,
                                  min_detection_confidence=.3) as detector:
        result = detector.process(arr)
    if not result.multi_hand_landmarks:
        return None
    best = max(zip(result.multi_hand_landmarks, result.multi_handedness, strict=True),
               key=lambda pair: pair[1].classification[0].score)[0]
    return np.float32([(p.x * image.width, p.y * image.height) for p in best.landmark])


def canonicalize(rgb, pts):
    import cv2

    pts = np.float32(pts)
    v1, v2 = pts[5] - pts[0], pts[17] - pts[0]
    # Mirror so the thumb is always on the right; left/right hands then share one frame.
    mirrored = bool(v1[0] * v2[1] - v1[1] * v2[0] > 0)
    if mirrored:
        rgb = rgb[:, ::-1].copy()
        pts = pts.copy()
        pts[:, 0] = rgb.shape[1] - 1 - pts[:, 0]
    keys = list(CANON)
    matrix, _ = cv2.estimateAffinePartial2D(np.float32([pts[k] for k in keys]),
                                            np.float32([CANON[k] for k in keys]) * SIZE,
                                            method=cv2.LMEDS)
    warped = cv2.warpAffine(rgb, matrix, (SIZE, SIZE), flags=cv2.INTER_CUBIC,
                            borderMode=cv2.BORDER_REFLECT)
    return warped, cv2.transform(pts[None], matrix)[0], matrix, mirrored, rgb, pts


class Frame:
    def __init__(self, cp):
        self.o = cp[17]
        self.U = cp[5] - cp[17]
        self.V = cp[0] - (cp[5] + cp[17]) / 2
        self.W = float(np.linalg.norm(self.U))

    def xy(self, u, v):
        return self.o + u * self.U + v * self.V


def palm_mask(warped, cp, frame):
    import cv2

    h, w = warped.shape[:2]
    poly = np.float32([frame.xy(-0.10, -0.06), frame.xy(1.04, -0.08), cp[2], cp[1],
                       frame.xy(0.82, 1.02), frame.xy(0.10, 1.02), frame.xy(-0.14, 0.55)])
    hull = np.zeros((h, w), np.uint8)
    cv2.fillPoly(hull, [np.int32(cv2.convexHull(poly))], 1)
    marks = np.full((h, w), cv2.GC_BGD, np.uint8)
    marks[cv2.dilate(hull, np.ones((41, 41), np.uint8)) == 1] = cv2.GC_PR_BGD
    marks[hull == 1] = cv2.GC_PR_FGD
    core = np.zeros((h, w), np.uint8)
    cv2.fillPoly(core, [np.int32([frame.xy(.1, .1), frame.xy(.9, .1), frame.xy(.8, .85),
                                  frame.xy(.15, .85)])], 1)
    marks[core == 1] = cv2.GC_FGD
    try:
        cv2.grabCut(warped, marks, None, np.zeros((1, 65)), np.zeros((1, 65)), 5,
                    cv2.GC_INIT_WITH_MASK)
        skin = np.isin(marks, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8)
    except cv2.error:
        skin = hull
    mask = cv2.morphologyEx(skin & hull, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count > 1:
        mask = (labels == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
    return mask


def ridge_evidence(warped, mask, width):
    """Shading-flattened Sato+Frangi dark-ridge response, scaled to the palm width."""
    import cv2
    from skimage.filters import frangi, sato

    lum = cv2.cvtColor(warped, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)
    gray = .5 * lum + .5 * warped[..., 1].astype(np.float32)
    flat = gray / (cv2.GaussianBlur(gray, (0, 0), .10 * width) + 1)
    scale = width / 400
    sigmas = (2.0 * scale, 3.2 * scale, 4.8 * scale)
    size = int(.07 * width) | 1
    inner = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    # Absolute crease contrast before any stretching: a featureless palm must not have its
    # noise normalized up into confident creases.
    raw = sato(flat, sigmas=sigmas, black_ridges=True)[inner > 0]
    confidence = float(np.clip(np.percentile(raw, 99.5) / ABSOLUTE_CONTRAST, 0, 1)) if raw.size else 0
    lo, hi = np.percentile(flat[mask > 0], (1, 99))
    flat = np.clip((flat - lo) / max(hi - lo, 1e-6), 0, 1)
    flat = cv2.createCLAHE(2.0, (8, 8)).apply(np.uint8(flat * 255)).astype(np.float32) / 255

    def norm(response):
        response = response * inner
        return np.clip(response / max(np.percentile(response[inner > 0], 99.5), 1e-9), 0, 1)

    fused = .6 * norm(sato(flat, sigmas=sigmas, black_ridges=True)) + \
        .4 * norm(frangi(flat, sigmas=sigmas, black_ridges=True, beta=.5, gamma=None))
    fused = np.clip(fused / max(np.percentile(fused[inner > 0], 99.5), 1e-9), 0, 1) * confidence
    return fused.astype(np.float32), inner


def _corridor(frame, centre):
    from scipy.ndimage import gaussian_filter1d

    p = np.float32([frame.xy(u, v) for u, v in centre])
    s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
    ss = np.linspace(0, s[-1], int(s[-1]))
    x = gaussian_filter1d(np.interp(ss, s, p[:, 0]), 6, mode='nearest')
    y = gaussian_filter1d(np.interp(ss, s, p[:, 1]), 6, mode='nearest')
    tx, ty = np.gradient(x), np.gradient(y)
    norm = np.hypot(tx, ty) + 1e-9
    return x, y, -ty / norm, tx / norm


def _straighten(source, x, y, nx, ny, half):
    import cv2

    t = np.arange(-half, half + 1, dtype=np.float32)
    mapx = (x[None, :] + t[:, None] * nx[None, :]).astype(np.float32)
    mapy = (y[None, :] + t[:, None] * ny[None, :]).astype(np.float32)
    strip = cv2.remap(source.astype(np.float32), mapx, mapy, cv2.INTER_LINEAR, borderValue=-1)
    return np.where(strip < -.99, -.5, strip), mapx, mapy


def _local_dp(strip, tau, prior):
    """Best continuous track across the straightened corridor (local alignment, |dt| <= 1)."""
    rows, cols = strip.shape
    gain = strip - tau - prior[:, None]
    score = np.full((rows, cols), -1e9)
    back = np.full((rows, cols), -1)
    score[:, 0] = np.maximum(gain[:, 0], 0)
    index = np.arange(rows)
    for j in range(1, cols):
        best = np.full(rows, -1e9)
        arg = np.zeros(rows, int)
        for d in range(-MAX_STEP, MAX_STEP + 1):
            prev = np.roll(score[:, j - 1], d) - LAMBDA * abs(d)
            if d > 0:
                prev[:d] = -1e9
            if d < 0:
                prev[d:] = -1e9
            better = prev > best
            best[better] = prev[better]
            arg[better] = (index - d)[better]
        fresh = best <= 0
        score[:, j] = np.where(fresh, 0, best) + gain[:, j]
        back[:, j] = np.where(fresh, -1, arg)
    t, j = np.unravel_index(np.argmax(score), score.shape)
    track = []
    while j >= 0 and t >= 0:
        track.append((t, j))
        t = back[t, j]
        j -= 1
    return np.array(track[::-1])


def _extend(track, strip, low):
    """Hysteresis: continue both ends column by column while the crease stays above `low`."""
    rows, cols = strip.shape
    head, tail = [], []
    for step, out in ((1, tail), (-1, head)):
        t, j = track[-1] if step == 1 else track[0]
        while 0 <= j + step < cols:
            j += step
            options = [r for r in (t - 1, t, t + 1) if 0 <= r < rows]
            t = max(options, key=lambda r: strip[r, j])
            if strip[t, j] < low:
                break
            out.append((t, j))
    return np.array(head[::-1] + [tuple(p) for p in track] + tail)


def combine(ridge, evidence, name):
    """Learned per-line probability lifts its own line and suppresses the other lines."""
    if not evidence or name not in evidence:
        return ridge
    others = [v for k, v in evidence.items() if k != name]
    rival = np.max(others, axis=0) if others else 0
    weight = LINES[name].get('classes', 1)
    return np.clip(ridge + weight * (.6 * evidence[name] - .4 * rival), 0, 1)


def _side(path, shape, frame, below):
    """Everything below (towards the wrist) or above a mostly transverse path, plus its width."""
    import cv2

    ext = np.concatenate([[path[0] + (path[0] - path[min(5, len(path) - 1)]) * 40], path,
                          [path[-1] + (path[-1] - path[max(-6, -len(path))]) * 40]])
    edge = SIZE * 2 if below else -SIZE
    poly = np.concatenate([ext, [[ext[-1][0], edge], [ext[0][0], edge]]])
    side = np.zeros(shape, np.uint8)
    cv2.fillPoly(side, [np.int32(poly)], 1)
    # Include the crease's full width so the other line cannot ride either of its edges.
    margin = max(3, int(.08 * frame.W)) | 1
    side = cv2.dilate(side, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (margin, margin)))
    return side.astype(bool)


def _continues(a, b, frame):
    """True when b starts where a ends (or vice versa) in the same direction: one crease."""
    def ends(path):
        k = min(8, len(path) - 1)
        return [(path[0], path[0] - path[k]), (path[-1], path[-1] - path[-1 - k])]

    for pa, da in ends(a):
        for pb, db in ends(b):
            gap = np.linalg.norm(pa - pb) / frame.W
            # Outward tangents of two touching pieces of one crease point in opposite ways.
            cosine = float(da @ db) / max(np.linalg.norm(da) * np.linalg.norm(db), 1e-6)
            if gap < .08 and cosine < -.85:
                return True
    return False


def trace_canonical(warped, cp, evidence=None, crease=None, crease_weight=.6):
    """Trace every line in the canonical palm.

    `evidence` maps line name -> probability map; `crease` is a line-agnostic crease
    probability (a learned model or a reviewed label mask) blended into the filter ridge map.
    """
    import cv2
    from scipy.ndimage import gaussian_filter1d

    frame = Frame(cp)
    mask = palm_mask(warped, cp, frame)
    filtered, inner = ridge_evidence(warped, mask, frame.W)

    def blended(name):
        if crease is None:
            return filtered
        # Learned crease maps follow labels that mostly mark the three major creases, so the
        # thin vertical lines keep more of the photo filter's own evidence.
        weight = crease_weight if crease_weight >= 1 else crease_weight * LINES[name].get('learned', 1)
        return np.clip(((1 - weight) * filtered + weight * crease) * inner, 0, 1).astype(np.float32)

    ridge = blended('head')

    def trace(name, occupied, forbid=None):
        """One line in its corridor -> (TracedLine, raw path or None, DP score)."""
        spec = LINES[name]
        allowed = np.where(inner > 0, combine(blended(name), evidence, name), -.5)
        if forbid is not None:
            allowed = np.where(forbid, -.5, allowed)
        x, y, nx, ny = _corridor(frame, spec['c'])
        half = int(spec['hw'] * frame.W)
        strip, mapx, mapy = _straighten(allowed - .8 * occupied, x, y, nx, ny, half)
        prior = MU * (np.abs(np.arange(-half, half + 1)) / max(half, 1)) ** 2
        core = _local_dp(strip, spec['tau'], prior)
        if len(core) < 2:
            return TracedLine(name, False), None, 0.0
        score = float(np.sum(strip[core[:, 0], core[:, 1]] - spec['tau'] - prior[core[:, 0]]))
        # Lines may meet (life and head share an origin), so the ends may run onto used creases.
        shared, _, _ = _straighten(allowed, x, y, nx, ny, half)
        track = _extend(core, shared, EXTEND_TAU)
        xs, ys = mapx[track[:, 0], track[:, 1]], mapy[track[:, 0], track[:, 1]]
        path = np.stack([xs, ys], 1)
        length = len(path) / frame.W
        support = float(np.mean(strip[core[:, 0], core[:, 1]]))
        visible = length > MIN_LENGTH[name] and support > spec['tau'] + .05
        smooth = np.stack([gaussian_filter1d(xs, 7, mode='nearest'),
                           gaussian_filter1d(ys, 7, mode='nearest')], 1)[::4]
        line = TracedLine(name, visible, round(length, 3), round(support, 3),
                          [tuple(map(float, p)) for p in smooth])
        return line, path if visible else None, score if visible else 0.0

    def occupy(occupied, name, path):
        band = np.zeros(ridge.shape, np.uint8)
        # Keep the next lines off this crease; the life line also blocks its parallel flank.
        width = .10 if name == 'life' else .04
        cv2.polylines(band, [np.int32(path)], False, 1, max(3, int(width * frame.W)))
        return np.maximum(occupied, band.astype(np.float32))

    # Heart and head are assigned together: the heart lies distal (towards the fingers) to the
    # head. Either line may claim a shared crease first; keep the order with more total evidence.
    empty = np.zeros(ridge.shape, np.float32)
    options = []
    for first, second, below in (('head', 'heart', True), ('heart', 'head', False)):
        a, a_path, a_score = trace(first, empty)
        held = occupy(empty, first, a_path) if a_path is not None else empty
        forbid = _side(a_path, ridge.shape, frame, below) if a_path is not None else None
        b, b_path, b_score = trace(second, held, forbid)
        total = a_score + b_score
        if a_path is not None and b_path is not None and _continues(a_path, b_path, frame):
            total = -np.inf  # one crease cut in two is not a heart/head pair
        options.append((total, {first: (a, a_path), second: (b, b_path)}))
        if DEBUG_JOINT:
            print('joint', first, round(a_score, 1), second, round(b_score, 1), 'total', total)
    # The head crease is the more reliably present one, so heart-first must clearly win.
    chosen = options[1][1] if options[1][0] > JOINT_MARGIN * max(options[0][0], 0) else options[0][1]
    lines = {name: chosen[name][0] for name in ('head', 'heart')}
    occupied = empty
    for name in ('head', 'heart'):
        if chosen[name][1] is not None:
            occupied = occupy(occupied, name, chosen[name][1])
    for name in ORDER:
        if name in lines:
            continue
        lines[name], path, _ = trace(name, occupied)
        if path is not None:
            occupied = occupy(occupied, name, path)
    lines = {name: lines[name] for name in ORDER}
    return lines, ridge


# Short secondary creases found as several separate segments inside an anatomical region.
# obstacle (장해선): roughly transverse creases on the thumb mount, on the thumb side of the life
# line; marriage (결혼선): short transverse creases on the little-finger edge above the heart line.
MINOR = {
    'obstacle': dict(max_angle=40, min_length=.18, min_support=.45, limit=3),
    'marriage': dict(max_angle=30, min_length=.06, min_support=.45, limit=2),
}


MAX_WIGGLE = .012


def _uv(frame, points):
    basis = np.stack([frame.U, frame.V], 1)
    return np.linalg.solve(basis, (np.float32(points) - frame.o).T).T


def _segments(evidence, region, frame, spec):
    import cv2
    from scipy.ndimage import gaussian_filter1d
    from skimage.morphology import skeletonize

    skeleton = skeletonize((evidence > .35) & region)
    count, labels = cv2.connectedComponents(skeleton.astype(np.uint8), connectivity=8)
    found = []
    for index in range(1, count):
        ys, xs = np.nonzero(labels == index)
        if len(xs) < 4:
            continue
        points = np.stack([xs, ys], 1).astype(np.float32)
        centre = points.mean(0)
        _, _, axes = np.linalg.svd(points - centre, full_matrices=False)
        axis = axes[0]
        along = (points - centre) @ axis
        length = float(np.ptp(along)) / frame.W
        # Angle against the palm's transverse axis (pinky MCP -> index MCP).
        cosine = abs(float(axis @ frame.U)) / frame.W
        angle = float(np.degrees(np.arccos(np.clip(cosine, 0, 1))))
        support = float(evidence[ys, xs].mean())
        # Skin texture yields wiggly ridge chains; a crease stays close to one smooth course.
        wiggle = float(np.sqrt(np.mean(((points - centre) @ axes[1]) ** 2))) / frame.W
        if (length < spec['min_length'] or angle > spec['max_angle']
                or support < spec['min_support'] or wiggle > MAX_WIGGLE):
            continue
        order = np.argsort(along)
        xs_sorted = gaussian_filter1d(points[order, 0], 2, mode='nearest')
        ys_sorted = gaussian_filter1d(points[order, 1], 2, mode='nearest')
        path = np.stack([xs_sorted, ys_sorted], 1)[::3]
        found.append((length * support, TracedLine('', True, round(length, 3), round(support, 3),
                                                    [tuple(map(float, p)) for p in path])))
    found.sort(key=lambda item: -item[0])
    kept = []
    for _, line in found:
        # One crease often breaks into parallel skeleton fragments; keep the strongest.
        mine = np.float32(line.canonical)
        if any(np.median(np.min(np.linalg.norm(mine[:, None] - np.float32(other.canonical)[None], axis=2),
                                axis=1)) < .035 * frame.W for other in kept):
            continue
        kept.append(line)
    return kept[:spec['limit']]


def trace_minor(warped, cp, lines):
    """Secondary creases from the photo filter only (learned maps were trained on major lines)."""
    frame = Frame(cp)
    mask = palm_mask(warped, cp, frame)
    evidence, inner = ridge_evidence(warped, mask, frame.W)
    h, w = evidence.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    uv = _uv(frame, np.stack([xx.ravel(), yy.ravel()], 1)).reshape(h, w, 2)
    u, v = uv[..., 0], uv[..., 1]
    inside = inner > 0
    minor = {}
    life, heart = lines.get('life'), lines.get('heart')
    if life is not None and life.visible:
        lu = _uv(frame, life.canonical)
        order = np.argsort(lu[:, 1])
        life_u = np.interp(v, lu[order, 1], lu[order, 0], left=np.nan, right=np.nan)
        thumb_side = (u > life_u + .06) & (v > .35) & (v < .95)
        minor['obstacle'] = _segments(evidence, inside & np.nan_to_num(thumb_side, nan=0).astype(bool),
                                      frame, MINOR['obstacle'])
    else:
        minor['obstacle'] = []
    ceiling = np.full_like(v, .05)
    if heart is not None and heart.visible:
        hu = _uv(frame, heart.canonical)
        order = np.argsort(hu[:, 0])
        ceiling = np.interp(u, hu[order, 0], hu[order, 1]) - .04
    edge = (u > -.25) & (u < .15) & (v > -.15) & (v < ceiling)
    minor['marriage'] = _segments(evidence, inside & edge, frame, MINOR['marriage'])
    return minor


def trace_palm(image: Image.Image, landmarks=None, evidence_model=None, minor=True) -> PalmTrace | None:
    """Trace lines on a photo. Returns None when no hand is found or a dependency is missing."""
    try:
        import cv2
    except ImportError:
        return None
    rgb = np.asarray(image.convert('RGB'))
    if landmarks is None:
        try:
            landmarks = _hand_landmarks(image)
        except ImportError:
            return None
    if landmarks is None:
        return None
    warped, cp, matrix, mirrored, oriented, points = canonicalize(rgb, landmarks)
    # Evidence models see the thumb-right photo and return maps in the canonical palm frame.
    evidence = evidence_model(oriented, points, matrix, warped) if evidence_model else None
    crease = evidence.pop('crease', None) if evidence else None
    lines, ridge = trace_canonical(warped, cp, evidence, crease)
    minor = trace_minor(warped, cp, lines) if minor else {}
    inverse = cv2.invertAffineTransform(matrix)
    h, w = rgb.shape[:2]
    for line in list(lines.values()) + [m for group in minor.values() for m in group]:
        if not line.canonical:
            continue
        back = cv2.transform(np.float32(line.canonical)[None], inverse)[0]
        if mirrored:
            back[:, 0] = w - 1 - back[:, 0]
        line.points = [(float(np.clip(x / w, 0, 1)), float(np.clip(y / h, 0, 1))) for x, y in back]
    return PalmTrace(mirrored, lines, minor, warped, ridge, matrix)
