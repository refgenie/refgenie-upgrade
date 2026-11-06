#!/usr/bin/env python3
"""Export a legacy-to-GA4GH genome digest lookup table.

Reads two sources and joins them by genome alias:
  A) Legacy hex digests from refgenomes.databio.org/config/refgenie_config_archive.yaml
  B) GA4GH digests from refgenie-registry/index/<alias>/fasta.yaml,
     falling back to genomes/**/<alias>.yaml seqcol.digest

Produces a JSON file mapping each legacy hex digest to its GA4GH equivalent,
with all known aliases.

Requires: PyYAML
"""

import json
import logging
import sys
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Paths relative to workspace root (assumes this repo is in repos/refgenie-upgrade)
SCRIPT_DIR = Path(__file__).resolve().parent
UPGRADE_ROOT = SCRIPT_DIR.parent
WORKSPACE_ROOT = UPGRADE_ROOT.parent.parent
LEGACY_CONFIG = WORKSPACE_ROOT / "repos" / "refgenomes.databio.org" / "config" / "refgenie_config_archive.yaml"
REGISTRY_ROOT = WORKSPACE_ROOT / "repos" / "refgenie-registry"
INDEX_DIR = REGISTRY_ROOT / "index"
GENOMES_DIR = REGISTRY_ROOT / "genomes"
OUTPUT_FILE = SCRIPT_DIR / "digest_map.json"


def load_legacy_genomes(config_path: Path) -> dict[str, dict]:
	"""Parse legacy config, returning {hex_digest: {"aliases": [str, ...]}}."""
	with open(config_path) as f:
		config = yaml.safe_load(f)

	genomes = {}
	for hex_digest, genome_data in config.get("genomes", {}).items():
		hex_digest = str(hex_digest)
		aliases = genome_data.get("aliases", [])
		genomes[hex_digest] = {"aliases": list(aliases)}
	return genomes


def find_ga4gh_digest_from_index(alias: str) -> str | None:
	"""Look up genome_digest from index/<alias>/fasta.yaml."""
	fasta_yaml = INDEX_DIR / alias / "fasta.yaml"
	if not fasta_yaml.exists():
		return None
	with open(fasta_yaml) as f:
		data = yaml.safe_load(f)
	return data.get("genome_digest")


def find_ga4gh_digest_from_genome_yaml(alias: str) -> str | None:
	"""Look up seqcol.digest from genomes/**/<alias>.yaml."""
	for yaml_file in GENOMES_DIR.rglob(f"{alias}.yaml"):
		with open(yaml_file) as f:
			data = yaml.safe_load(f)
		seqcol = data.get("seqcol", {})
		if isinstance(seqcol, dict):
			digest = seqcol.get("digest")
			if digest and digest != "compute":
				return digest
	return None


def find_genome_yaml_aliases(alias: str) -> list[str]:
	"""Get additional aliases from genomes/**/<alias>.yaml."""
	for yaml_file in GENOMES_DIR.rglob(f"{alias}.yaml"):
		with open(yaml_file) as f:
			data = yaml.safe_load(f)
		return data.get("aliases", [])
	return []


def export_digest_table() -> dict:
	"""Build the legacy-to-GA4GH digest lookup table."""
	if not LEGACY_CONFIG.exists():
		log.error(f"Legacy config not found: {LEGACY_CONFIG}")
		sys.exit(1)

	legacy_genomes = load_legacy_genomes(LEGACY_CONFIG)
	log.info(f"Loaded {len(legacy_genomes)} legacy genomes")

	result = {
		"version": 1,
		"description": (
			"Maps legacy refgenie hex genome digests to "
			"refgenie1 GA4GH sha512t24u base64url digests"
		),
		"genomes": {},
	}

	resolved = 0
	for hex_digest, info in legacy_genomes.items():
		legacy_aliases = info["aliases"]
		primary_alias = legacy_aliases[0] if legacy_aliases else None

		if not primary_alias:
			log.warning(f"Genome {hex_digest} has no aliases, skipping")
			continue

		# Try index first, then genome YAML
		ga4gh_digest = find_ga4gh_digest_from_index(primary_alias)
		if ga4gh_digest is None:
			ga4gh_digest = find_ga4gh_digest_from_genome_yaml(primary_alias)

		if ga4gh_digest is None:
			log.warning(f"No GA4GH digest for {primary_alias} ({hex_digest}), skipping")
			continue

		# Merge aliases from legacy config and genome YAML
		yaml_aliases = find_genome_yaml_aliases(primary_alias)
		all_aliases = list(legacy_aliases)
		for a in yaml_aliases:
			if a not in all_aliases:
				all_aliases.append(a)

		result["genomes"][hex_digest] = {
			"ga4gh_digest": ga4gh_digest,
			"aliases": all_aliases,
		}
		resolved += 1

	log.info(f"Resolved {resolved}/{len(legacy_genomes)} genomes")
	return result


def main():
	table = export_digest_table()

	output = OUTPUT_FILE
	if len(sys.argv) > 1:
		output = Path(sys.argv[1])

	with open(output, "w") as f:
		json.dump(table, f, indent=2)
		f.write("\n")

	log.info(f"Written to {output}")


if __name__ == "__main__":
	main()
