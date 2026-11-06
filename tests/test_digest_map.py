"""Tests for the legacy-to-GA4GH digest conversion utilities."""

import hashlib
import re

from refgenie_upgrade.digest_map import (
    hex_to_base64url,
    load_digest_map,
    resolve_legacy_digest,
)

# Known pair: hg38
HG38_LEGACY = "2230c535660fb4774114bfa966a62f823fdb6d21acf138d4"
HG38_GA4GH = "EiFob05aCWgVU_B_Ae0cypnQut3cxUP1"


class TestHexToBase64url:
    """hex_to_base64url re-encodes individual sequence digests."""

    def test_known_conversion(self):
        """An independently computed SHA-512/24 encodes identically both ways."""
        raw = hashlib.sha512(b"test").digest()[:24]
        hex_str = raw.hex()
        result = hex_to_base64url(hex_str)
        import base64

        padded = result + "=" * (-len(result) % 4)
        assert base64.urlsafe_b64decode(padded) == raw

    def test_output_length(self):
        """A 48-char hex digest (24 bytes) produces a 32-char base64url string."""
        hex_str = "a" * 48
        result = hex_to_base64url(hex_str)
        assert len(result) == 32

    def test_no_padding(self):
        """Output must not contain '=' padding characters."""
        result = hex_to_base64url("ab" * 24)
        assert "=" not in result

    def test_url_safe_chars(self):
        """Output uses base64url alphabet (- and _ instead of + and /)."""
        result = hex_to_base64url("ff" * 24)
        assert "+" not in result
        assert "/" not in result


class TestLoadDigestMap:
    """load_digest_map returns the bundled JSON with the correct shape."""

    def test_top_level_keys(self):
        table = load_digest_map()
        assert "version" in table
        assert "description" in table
        assert "genomes" in table
        assert table["version"] == 1

    def test_genomes_is_dict(self):
        table = load_digest_map()
        assert isinstance(table["genomes"], dict)
        assert len(table["genomes"]) > 0

    def test_every_key_is_48_char_hex(self):
        table = load_digest_map()
        hex_pattern = re.compile(r"^[0-9a-f]{48}$")
        for key in table["genomes"]:
            assert hex_pattern.match(key), f"Key {key!r} is not a 48-char hex string"

    def test_every_value_has_required_fields(self):
        table = load_digest_map()
        for key, value in table["genomes"].items():
            assert "ga4gh_digest" in value, f"Missing ga4gh_digest for {key}"
            assert "aliases" in value, f"Missing aliases for {key}"
            assert isinstance(value["aliases"], list)
            assert len(value["aliases"]) > 0
            assert len(value["ga4gh_digest"]) == 32, (
                f"GA4GH digest for {key} is {len(value['ga4gh_digest'])} chars, expected 32"
            )


class TestResolveLegacyDigest:
    """resolve_legacy_digest looks up genome digests."""

    def test_known_hit(self):
        result = resolve_legacy_digest(HG38_LEGACY)
        assert result == HG38_GA4GH

    def test_miss_returns_none(self):
        result = resolve_legacy_digest("0" * 48)
        assert result is None
