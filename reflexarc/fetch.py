"""First-run pet fetching from the public petdex catalog.

Pets are community art; they are not bundled with this repo. When a pet is
missing locally we pull it from the official petdex manifest into
pets/<slug>/ (pet.json + spritesheet).
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

MANIFEST_URL = "https://petdex.dev/api/manifest"
UA = {"User-Agent": "reflexarc/0.1 (+https://github.com)"}


def _get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_pet(slug: str, dest_root: Path, *, quiet: bool = False) -> Path:
    """Download a pet into dest_root/<slug>/. Returns its directory."""
    dest = dest_root / slug
    if (dest / "pet.json").exists():
        return dest

    if not quiet:
        print(f"[reflexarc] fetching pet '{slug}' from petdex...", flush=True)
    manifest = json.loads(_get(MANIFEST_URL).decode("utf-8"))
    entry = next((p for p in manifest.get("pets", []) if p.get("slug") == slug), None)
    if entry is None:
        raise FileNotFoundError(f"pet '{slug}' not found in petdex manifest")

    dest.mkdir(parents=True, exist_ok=True)
    pet_json = _get(entry["petJsonUrl"])
    meta = json.loads(pet_json.decode("utf-8"))

    sprite_bytes = _get(entry["spritesheetUrl"])
    ext = Path(entry["spritesheetUrl"]).suffix or ".webp"
    sprite_name = meta.get("spritesheetPath") or f"spritesheet{ext}"
    (dest / "pet.json").write_bytes(pet_json)
    (dest / sprite_name).write_bytes(sprite_bytes)

    if not quiet:
        print(f"[reflexarc] saved -> {dest}", flush=True)
    return dest
