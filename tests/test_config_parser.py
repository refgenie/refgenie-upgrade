"""Tests for the legacy config parser."""

from pathlib import Path

import pytest

from refgenie_upgrade.config_parser import (
    LegacyConfig,
    _is_hex_digest,
    parse_legacy_config,
)


class TestIsHexDigest:
    def test_valid_hex_digest(self):
        assert _is_hex_digest("7319f9237651755047bc40d7f7a9770d42a537e840f4e105")

    def test_too_short(self):
        assert not _is_hex_digest("7319f923")

    def test_not_hex(self):
        assert not _is_hex_digest("human_repeats")

    def test_48_chars_not_hex(self):
        assert not _is_hex_digest("z" * 48)


class TestParseV04Config:
    def test_parses_version(self, v04_config_path):
        config = parse_legacy_config(v04_config_path)
        assert config.config_version == 0.4

    def test_parses_genome_folder(self, v04_config_path):
        config = parse_legacy_config(v04_config_path)
        assert config.genome_folder == Path("/tmp/refgenie_test_data")

    def test_parses_servers(self, v04_config_path):
        config = parse_legacy_config(v04_config_path)
        assert config.genome_servers == ["http://refgenomes.databio.org"]

    def test_parses_genomes(self, v04_config_path):
        config = parse_legacy_config(v04_config_path)
        assert len(config.genomes) == 2

    def test_genome_digests(self, v04_config_path):
        config = parse_legacy_config(v04_config_path)
        digests = {g.digest for g in config.genomes}
        assert "7319f9237651755047bc40d7f7a9770d42a537e840f4e105" in digests
        assert "94e0d21feb576e6af61cd2a798ad30682ef2428bb7eabbb4" in digests

    def test_genome_aliases(self, v04_config_path):
        config = parse_legacy_config(v04_config_path)
        genome_map = {g.digest: g for g in config.genomes}
        hr = genome_map["7319f9237651755047bc40d7f7a9770d42a537e840f4e105"]
        assert "human_repeats" in hr.aliases

    def test_parses_assets(self, v04_config_path):
        config = parse_legacy_config(v04_config_path)
        genome_map = {g.digest: g for g in config.genomes}
        rcrsd = genome_map["94e0d21feb576e6af61cd2a798ad30682ef2428bb7eabbb4"]
        asset_names = {a.name for a in rcrsd.assets}
        assert "fasta" in asset_names
        assert "bowtie2_index" in asset_names

    def test_parses_tags(self, v04_config_path):
        config = parse_legacy_config(v04_config_path)
        genome_map = {g.digest: g for g in config.genomes}
        hr = genome_map["7319f9237651755047bc40d7f7a9770d42a537e840f4e105"]
        fasta = next(a for a in hr.assets if a.name == "fasta")
        assert len(fasta.tags) == 1
        assert fasta.tags[0].name == "default"

    def test_parses_seek_keys(self, v04_config_path):
        config = parse_legacy_config(v04_config_path)
        genome_map = {g.digest: g for g in config.genomes}
        hr = genome_map["7319f9237651755047bc40d7f7a9770d42a537e840f4e105"]
        fasta = next(a for a in hr.assets if a.name == "fasta")
        tag = fasta.tags[0]
        sk_names = {sk.name for sk in tag.seek_keys}
        assert "fasta" in sk_names
        assert "fai" in sk_names
        assert "chrom_sizes" in sk_names

    def test_parses_asset_children(self, v04_config_path):
        config = parse_legacy_config(v04_config_path)
        genome_map = {g.digest: g for g in config.genomes}
        rcrsd = genome_map["94e0d21feb576e6af61cd2a798ad30682ef2428bb7eabbb4"]
        fasta = next(a for a in rcrsd.assets if a.name == "fasta")
        tag = fasta.tags[0]
        assert len(tag.asset_children) == 1

    def test_parses_description(self, v04_config_path):
        config = parse_legacy_config(v04_config_path)
        genome_map = {g.digest: g for g in config.genomes}
        hr = genome_map["7319f9237651755047bc40d7f7a9770d42a537e840f4e105"]
        assert "human repeat" in hr.description.lower()


class TestParseV03Config:
    def test_parses_version(self, v03_config_path):
        config = parse_legacy_config(v03_config_path)
        assert config.config_version == 0.3

    def test_deduplicates_genomes(self, v03_config_path):
        """v0.3 has 4 entries (2 digest-keyed + 2 name-keyed) for 2 genomes."""
        config = parse_legacy_config(v03_config_path)
        assert len(config.genomes) == 2

    def test_merges_aliases(self, v03_config_path):
        """After deduplication, aliases from name-keyed entries are merged."""
        config = parse_legacy_config(v03_config_path)
        genome_map = {g.digest: g for g in config.genomes}
        hr = genome_map["7319f9237651755047bc40d7f7a9770d42a537e840f4e105"]
        assert "human_repeats" in hr.aliases

    def test_preserves_digest_keyed_genomes(self, v03_config_path):
        config = parse_legacy_config(v03_config_path)
        digests = {g.digest for g in config.genomes}
        assert "7319f9237651755047bc40d7f7a9770d42a537e840f4e105" in digests
        assert "94e0d21feb576e6af61cd2a798ad30682ef2428bb7eabbb4" in digests

    def test_genome_folder(self, v03_config_path):
        config = parse_legacy_config(v03_config_path)
        assert config.genome_folder == Path("/tmp/refgenie_test_data_v3")


class TestParseEdgeCases:
    def test_missing_config_raises(self):
        with pytest.raises(FileNotFoundError):
            parse_legacy_config(Path("/nonexistent/config.yaml"))

    def test_missing_genome_folder_defaults_to_config_dir(self, tmp_path):
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(
            "config_version: 0.4\ngenomes: {}\ngenome_servers: []\n"
        )
        config = parse_legacy_config(config_file)
        # When genome_folder is empty, should not raise
        assert config.genome_folder is not None
