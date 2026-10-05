"""Independent spherical oracle and exact identity validation."""

import hashlib
import math

from engine.spatial.metadata import EARTH_RADIUS_METRES


def spherical_distance(latitude, longitude, center):
    first, second = math.radians(latitude), math.radians(center[0])
    latitude_gap = math.radians(latitude - center[0])
    longitude_gap = math.radians(longitude - center[1])
    value = (math.sin(latitude_gap / 2) ** 2 + math.cos(first) * math.cos(second)
             * math.sin(longitude_gap / 2) ** 2)
    return 2 * EARTH_RADIUS_METRES * math.atan2(math.sqrt(max(0, value)), math.sqrt(max(0, 1 - value)))


def identities_hash(identities):
    return hashlib.sha256(",".join(str(identity) for identity in sorted(identities)).encode()).hexdigest()


def oracle(points, center, radii, neighbors):
    distances = sorted((spherical_distance(row[2], row[3], center), row[0]) for row in points)
    expected = {}
    for radius in radii:
        identities = [identity for actual, identity in distances if actual < radius]
        expected[f"radius:{radius}"] = {"count": len(identities), "ids_sha256": identities_hash(identities)}
    for k in neighbors:
        pairs = [(identity, actual) for actual, identity in distances[:k]]
        expected[f"knn:{k}"] = {"count": len(pairs), "ids_sha256": identities_hash(identity for identity, _ in pairs), "pairs": pairs}
    return expected


def validate(pairs, expected, points_by_id, center, *, tolerance=1e-5):
    identities = [identity for identity, _ in pairs]
    if len(set(identities)) != len(identities) or len(pairs) != expected["count"] or identities_hash(identities) != expected["ids_sha256"]:
        raise ValueError("Spatial result identities differ from the exhaustive oracle")
    for identity, actual in pairs:
        row = points_by_id[identity]
        if not math.isclose(actual, spherical_distance(row[2], row[3], center), rel_tol=0, abs_tol=tolerance):
            raise ValueError("Spatial result distance differs from the spherical oracle")
    if "pairs" in expected and [identity for identity, _ in pairs] != [identity for identity, _ in expected["pairs"]]:
        raise ValueError("k-NN ordering or tie policy differs from the oracle")


def uses_gist(plan):
    if plan.get("Index Name") == "points_location_gist" and plan.get("Node Type") in {"Index Scan", "Bitmap Index Scan", "Index Only Scan"}:
        return True
    return any(uses_gist(child) for child in plan.get("Plans", []))


def peak_rss_bytes(status=None):
    if status is None:
        with open("/proc/self/status", encoding="utf-8") as source:
            status = source.read()
    line = next(line for line in status.splitlines() if line.startswith("VmHWM:"))
    return int(line.split()[1]) * 1024
