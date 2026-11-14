"""Certified piecewise closest projection onto a polygonal ring.

The arrangement costs O(D R**3) in the worst case for D drawn segments
and R ring edges. Explicit work limits reject oversized arrangements.
"""
import numpy as np


def project_pieces(points, ring, *, work_limit=2000000):
    """Return (drawn start, drawn end, ring start, ring end) pieces.

    Ring stations are unwrapped continuously. Reject nonunique projections,
    discontinuities, reversals, and numerical degeneracy. Shared vertices
    may have two equivalent nearest edges. No sampling certifies an interval:
    distance-polynomial roots partition every possible change of owner.
    """
    points, ring = np.asarray(points, float), np.asarray(ring, float)
    if any(a.ndim != 2 or a.shape[1] != 2 or not np.isfinite(a).all()
           for a in (points, ring)):
        raise ValueError('Expected finite XY coordinates')
    if len(points) < 2 or len(ring) < 3:
        raise ValueError('Degenerate projection geometry')
    if not np.array_equal(ring[0], ring[-1]):
        ring = np.vstack((ring, ring[0]))
    edges = np.diff(ring, axis=0)
    lengths = np.linalg.norm(edges, axis=1)
    if len(points) < 2 or len(edges) < 3 or np.any(lengths == 0):
        raise ValueError('Degenerate projection geometry')
    stations = np.r_[0., np.cumsum(lengths)]
    total = stations[-1]
    eps = 128 * np.finfo(float).eps * max(total, np.max(np.abs(ring)), 1.)
    result, arc, work = [], 0., 0
    for p, q in zip(points, points[1:]):
        v = q - p
        span = np.linalg.norm(v)
        if span <= eps:
            raise ValueError('Degenerate drawn segment')
        alpha = np.sum((p - ring[:-1]) * edges, axis=1) / lengths**2
        beta = edges @ v / lengths**2
        cuts = [0., 1.]
        for a, b in zip(alpha, beta):
            if b:
                cuts.extend(t for t in (-a/b, (1-a)/b) if 0 < t < 1)
        cuts = sorted(set(cuts))
        for lo, hi in zip(cuts, cuts[1:]):
            mid = (lo+hi)/2
            active = (alpha+beta*mid > 0) & (alpha+beta*mid < 1)
            a = np.where(active, alpha, np.clip(alpha+beta*mid, 0, 1))
            b = np.where(active, beta, 0.)
            base = p - (ring[:-1] + a[:, None]*edges)
            slope = v - b[:, None]*edges
            poly = np.column_stack((np.sum(slope*slope, axis=1),
                                    2*np.sum(base*slope, axis=1),
                                    np.sum(base*base, axis=1)))
            roots = [lo, hi]
            for i in range(len(edges)):
                for j in range(i):
                    work += 1
                    if work > work_limit:
                        raise ValueError('Projection arrangement work limit exceeded')
                    coefficients = np.trim_zeros(poly[i]-poly[j], 'f')
                    if len(coefficients) > 1:
                        for root in np.roots(coefficients):
                            if abs(root.imag) <= 1e-12 and lo < root.real < hi:
                                roots.append(float(root.real))
            roots = sorted(set(roots))
            for left, right in zip(roots, roots[1:]):
                t = (left+right)/2
                dist = poly @ np.array([t*t, t, 1.])
                best = int(np.argmin(dist))
                near = np.flatnonzero(abs(dist-dist[best]) <= eps*eps)
                projected = ring[:-1] + (a+b*t)[:, None]*edges
                if any(np.linalg.norm(projected[k]-projected[best]) > eps for k in near):
                    raise ValueError('Ambiguous nearest perimeter edges')
                s0 = stations[best] + lengths[best]*(a[best]+b[best]*left)
                s1 = stations[best] + lengths[best]*(a[best]+b[best]*right)
                if result:
                    shift = round((result[-1][3]-s0)/total)*total
                    s0, s1 = s0+shift, s1+shift
                    if abs(s0-result[-1][3]) > eps:
                        raise ValueError('Discontinuous perimeter projection')
                result.append((arc+span*left, arc+span*right, s0, s1))
        arc += span
    delta = np.array([p[3]-p[2] for p in result])
    if np.any(delta > eps) and np.any(delta < -eps):
        raise ValueError('Backwards perimeter projection')
    if abs(result[-1][3]-result[0][2]) <= eps:
        raise ValueError('Zero projected span')
    return result


def invert_station(pieces, station):
    """Invert a certified station; refuse a plateau with multiple preimages."""
    answers = []
    for a, b, u, v in pieces:
        if min(u, v) <= station <= max(u, v):
            if u == v:
                raise ValueError('Ambiguous plateau cut')
            answers.append(a+(b-a)*(station-u)/(v-u))
    if not answers or max(answers)-min(answers) > 1e-9:
        raise ValueError('Station has no unique drawn preimage')
    return answers[0]
