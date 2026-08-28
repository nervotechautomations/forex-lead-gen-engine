#!/usr/bin/env python3
"""
face_check.py — Detects whether a profile avatar contains a face.

Uses OpenCV Haar cascades (frontal + profile) on the downloaded avatar.
Conservative by design: an avatar with no detectable face -> faceless
(chart/meme/logo account) -> reject, per "face-content influencer only".

Usage:
    python3 face_check.py <image_url_or_path>     -> exit 0 if face found
    python3 face_check.py --json <url>            -> {"face": bool, "faces": n}

Exit codes: 0 = face found, 1 = no face, 2 = error/unavailable.
"""
import sys
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def load_image(url_or_path: str):
    """Return numpy BGR image or None."""
    try:
        import numpy as np
        import cv2
    except ImportError:
        return None
    try:
        if url_or_path.startswith(("http://", "https://")):
            req = urllib.request.Request(url_or_path, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = np.frombuffer(r.read(), dtype=np.uint8)
        else:
            raw = np.fromfile(url_or_path, dtype=np.uint8)
        img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None


def has_face(url_or_path: str):
    """Return (bool, face_count). False on any error (conservative)."""
    try:
        import cv2
        img = load_image(url_or_path)
        if img is None:
            return False, 0
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        cascade_dir = cv2.data.haarcascades
        frontal = cv2.CascadeClassifier(cascade_dir + "haarcascade_frontalface_default.xml")
        profile = cv2.CascadeClassifier(cascade_dir + "haarcascade_profileface.xml")
        count = 0
        h, w = gray.shape
        # require the face to be a substantial part of the avatar (>=1/3 of the
        # smaller dimension). Real people's avatars are mostly face; cartoon /
        # stylized / logo avatars with a small face icon fail this threshold.
        min_side = max(32, min(h, w) // 3)
        for cascade in (frontal, profile):
            faces = cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=6,
                minSize=(min_side, min_side),
            )
            count += len(faces)
        return count > 0, count
    except Exception:
        return False, 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--json"]
    if not args:
        print("usage: face_check.py <url|path> [--json]")
        sys.exit(2)
    url = args[0]
    face, n = has_face(url)
    if "--json" in sys.argv:
        print(f'{{"face": {str(face).lower()}, "faces": {n}}}')
    else:
        print("FACE" if face else "NO FACE", f"(detected: {n})")
    sys.exit(0 if face else 1)
