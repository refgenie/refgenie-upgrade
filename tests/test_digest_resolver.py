"""Tests for the digest resolver."""

from pathlib import Path
from unittest.mock import patch

import pytest

from refgenie_upgrade.digest_resolver import (
    DigestResolution,
    _find_fasta_file,
    resolve_genome_digest,
)


class TestResolveGenomeDigest:
    def test_lookup_table_hit(self):
        """A known hex digest should resolve via the lookup table."""
        # Use a digest that is in the lookup table
        with patch(
            "refgenie_upgrade.digest_resolver.resolve_legacy_digest",
            return_value="test_ga4gh_digest_abc123",
        ):
            result = resolve_genome_digest("a" * 48)
            assert result.method == "lookup_table"
            assert result.ga4gh_digest == "test_ga4gh_digest_abc123"
            assert result.legacy_hex == "a" * 48

    def test_lookup_table_miss_no_folder(self):
        """Miss with no genome folder should return unresolved."""
        with patch(
            "refgenie_upgrade.digest_resolver.resolve_legacy_digest",
            return_value=None,
        ):
            result = resolve_genome_digest("b" * 48)
            assert result.method == "unresolved"
            assert result.ga4gh_digest is None

    def test_lookup_table_miss_with_fasta(self, tmp_path):
        """Miss with FASTA available should try computation."""
        # Create a fake FASTA file in the expected location
        hex_digest = "c" * 48
        fasta_dir = tmp_path / "data" / hex_digest / "fasta" / "default"
        fasta_dir.mkdir(parents=True)
        fasta_file = fasta_dir / f"{hex_digest}.fa"
        fasta_file.write_text(">chr1\nACGT\n")

        with patch(
            "refgenie_upgrade.digest_resolver.resolve_legacy_digest",
            return_value=None,
        ):
            with patch(
                "refgenie_upgrade.digest_resolver._compute_seqcol_digest",
                return_value="computed_digest_xyz",
            ):
                result = resolve_genome_digest(hex_digest, genome_folder=tmp_path)
                assert result.method == "fasta_computation"
                assert result.ga4gh_digest == "computed_digest_xyz"


class TestFindFastaFile:
    def test_finds_exact_fasta(self, tmp_path):
        hex_digest = "d" * 48
        fasta_dir = tmp_path / "data" / hex_digest / "fasta" / "default"
        fasta_dir.mkdir(parents=True)
        fasta_file = fasta_dir / f"{hex_digest}.fa"
        fasta_file.write_text(">chr1\nACGT\n")

        result = _find_fasta_file(tmp_path, hex_digest)
        assert result == fasta_file

    def test_finds_gzipped_fasta(self, tmp_path):
        hex_digest = "e" * 48
        fasta_dir = tmp_path / "data" / hex_digest / "fasta" / "default"
        fasta_dir.mkdir(parents=True)
        fasta_file = fasta_dir / f"{hex_digest}.fa.gz"
        fasta_file.write_text("fake gzipped content")

        result = _find_fasta_file(tmp_path, hex_digest)
        assert result == fasta_file

    def test_returns_none_when_missing(self, tmp_path):
        result = _find_fasta_file(tmp_path, "f" * 48)
        assert result is None

    def test_finds_via_glob(self, tmp_path):
        hex_digest = "a" * 48
        fasta_dir = tmp_path / "data" / hex_digest / "fasta" / "default"
        fasta_dir.mkdir(parents=True)
        fasta_file = fasta_dir / "genome.fa"
        fasta_file.write_text(">chr1\nACGT\n")

        result = _find_fasta_file(tmp_path, hex_digest)
        assert result == fasta_file
