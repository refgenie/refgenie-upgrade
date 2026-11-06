"""Legacy-to-GA4GH genome digest conversion utilities.

Self-contained within refgenie-upgrade so the one-time migration tool carries
its own knowledge of the (closed, end-of-life) legacy digest set, rather than
depending on refgenie1 to ship legacy-migration data.

Provides two mechanisms:

1. ``hex_to_base64url`` -- re-encodes individual *sequence* digests from
   hex to base64url.  Both encodings represent the same SHA-512/24 bytes,
   so the conversion is lossless.  This does NOT work for collection-level
   genome digests because the two systems hash different inputs.

2. ``load_digest_map`` / ``resolve_legacy_digest`` -- a static lookup table
   that maps legacy 48-char hex *genome* digests to their GA4GH 32-char
   base64url equivalents.  Built from the public refgenie registry.
"""

import base64
import binascii
import json
from functools import lru_cache
from importlib.resources import files as pkg_files


def hex_to_base64url(hex_digest: str) -> str:
    """Convert a hex-encoded SHA-512/24 digest to GA4GH base64url encoding.

    Works for individual SEQUENCE digests only.  Collection-level genome
    digests use different serialization schemes and cannot be re-encoded
    -- use the lookup table for those.
    """
    raw_bytes = binascii.unhexlify(hex_digest)
    return base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")


@lru_cache(maxsize=1)
def load_digest_map() -> dict:
    """Load the bundled legacy-to-GA4GH genome digest mapping."""
    data_file = pkg_files("refgenie_upgrade.data").joinpath("digest_map.json")
    return json.loads(data_file.read_text())


def resolve_legacy_digest(hex_digest: str) -> str | None:
    """Look up a legacy hex genome digest and return the GA4GH digest, or None."""
    table = load_digest_map()
    entry = table["genomes"].get(hex_digest)
    return entry["ga4gh_digest"] if entry else None
