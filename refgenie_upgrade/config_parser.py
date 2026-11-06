"""Parse legacy refgenie genome_config.yaml files (v0.3 and v0.4).

Uses raw PyYAML to avoid depending on refgenconf. The legacy config format
is stable and no longer evolving, so a simple parser suffices.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class LegacySeekKey:
    name: str
    value: str  # relative path or "." for directory


@dataclass
class LegacyTag:
    name: str  # e.g. "default"
    asset_path: str  # relative content dir name
    asset_digest: str  # MD5 of asset content
    seek_keys: list[LegacySeekKey] = field(default_factory=list)
    asset_parents: list[str] = field(default_factory=list)
    asset_children: list[str] = field(default_factory=list)


@dataclass
class LegacyAsset:
    name: str  # e.g. "fasta", "bwa_index"
    tags: list[LegacyTag] = field(default_factory=list)
    default_tag: str = "default"


@dataclass
class LegacyGenome:
    digest: str  # 48-char hex digest (primary key in v0.4)
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    assets: list[LegacyAsset] = field(default_factory=list)


@dataclass
class LegacyConfig:
    config_version: float  # 0.3 or 0.4
    genome_folder: Path
    genome_servers: list[str] = field(default_factory=list)
    genomes: list[LegacyGenome] = field(default_factory=list)


def _is_hex_digest(key: str) -> bool:
    """Check if a string looks like a 48-char hex digest."""
    if len(key) != 48:
        return False
    try:
        int(key, 16)
        return True
    except ValueError:
        return False


def _parse_tag(tag_name: str, tag_data: dict) -> LegacyTag:
    """Parse a single tag entry from the config."""
    if tag_data is None:
        tag_data = {}

    seek_keys = []
    raw_seek_keys = tag_data.get("seek_keys", {})
    if raw_seek_keys:
        for sk_name, sk_value in raw_seek_keys.items():
            seek_keys.append(LegacySeekKey(name=sk_name, value=str(sk_value)))

    parents = tag_data.get("asset_parents", [])
    if parents is None:
        parents = []
    children = tag_data.get("asset_children", [])
    if children is None:
        children = []

    return LegacyTag(
        name=tag_name,
        asset_path=str(tag_data.get("asset_path", "")),
        asset_digest=str(tag_data.get("asset_digest", "")),
        seek_keys=seek_keys,
        asset_parents=parents,
        asset_children=children,
    )


def _parse_asset(asset_name: str, asset_data: dict) -> LegacyAsset:
    """Parse a single asset entry from the config."""
    if asset_data is None:
        asset_data = {}

    tags = []
    raw_tags = asset_data.get("tags", {})
    if raw_tags:
        for tag_name, tag_data in raw_tags.items():
            tags.append(_parse_tag(tag_name, tag_data))

    return LegacyAsset(
        name=asset_name,
        tags=tags,
        default_tag=asset_data.get("default_tag", "default"),
    )


def _parse_genome(key: str, genome_data: dict, is_digest_key: bool) -> LegacyGenome:
    """Parse a single genome entry from the config."""
    if genome_data is None:
        genome_data = {}

    aliases = genome_data.get("aliases", [])
    if aliases is None:
        aliases = []

    if is_digest_key:
        digest = key
    else:
        # v0.3 name-keyed entry: the key IS the alias
        digest = key
        if key not in aliases:
            aliases = [key] + list(aliases)

    assets = []
    raw_assets = genome_data.get("assets", {})
    if raw_assets:
        for asset_name, asset_data in raw_assets.items():
            assets.append(_parse_asset(asset_name, asset_data))

    return LegacyGenome(
        digest=digest,
        aliases=list(aliases),
        description=genome_data.get("genome_description", ""),
        assets=assets,
    )


def _deduplicate_v03_genomes(genomes: list[LegacyGenome]) -> list[LegacyGenome]:
    """Deduplicate v0.3 genomes that appear under both digest and name keys.

    v0.3 configs list the same genome under its hex digest and under each
    alias name. Group them by matching asset_digest of the fasta tag. If no
    fasta tag exists, fall back to comparing genome descriptions.
    """
    # Build a mapping from asset_digest to genome entries
    groups: dict[str, list[LegacyGenome]] = {}
    ungrouped: list[LegacyGenome] = []

    for genome in genomes:
        fasta_digest = _get_fasta_digest(genome)
        if fasta_digest:
            groups.setdefault(fasta_digest, []).append(genome)
        else:
            ungrouped.append(genome)

    deduplicated = []
    for fasta_digest, group in groups.items():
        # Find the digest-keyed entry (the authoritative one)
        digest_entries = [g for g in group if _is_hex_digest(g.digest)]
        name_entries = [g for g in group if not _is_hex_digest(g.digest)]

        if digest_entries:
            primary = digest_entries[0]
            # Merge aliases from name-keyed entries
            all_aliases = set(primary.aliases)
            for name_entry in name_entries:
                all_aliases.update(name_entry.aliases)
                # The key itself is an alias for name entries
                all_aliases.add(name_entry.digest)
            primary.aliases = sorted(all_aliases)
            deduplicated.append(primary)
        else:
            # No digest-keyed entry; keep the first name-keyed entry
            primary = group[0]
            for other in group[1:]:
                primary.aliases = sorted(set(primary.aliases) | set(other.aliases) | {other.digest})
            deduplicated.append(primary)

    deduplicated.extend(ungrouped)
    return deduplicated


def _get_fasta_digest(genome: LegacyGenome) -> str | None:
    """Get the fasta asset_digest for a genome, if it has one."""
    for asset in genome.assets:
        if asset.name == "fasta":
            for tag in asset.tags:
                if tag.asset_digest:
                    return tag.asset_digest
    return None


def parse_legacy_config(config_path: Path) -> LegacyConfig:
    """Parse a legacy genome_config.yaml into structured data.

    Handles both v0.3 and v0.4 schemas. v0.3 genomes are keyed by
    name (not digest) and contain an 'aliases' list; v0.4 genomes
    are keyed by hex digest.

    Args:
        config_path: Path to the legacy genome_config.yaml file.

    Returns:
        LegacyConfig with all parsed genome, asset, tag, and seek key data.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the config file cannot be parsed.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ValueError(f"Empty or invalid config file: {config_path}")

    config_version = float(raw.get("config_version", 0.4))

    # Resolve genome_folder
    genome_folder_str = raw.get("genome_folder", "")
    if genome_folder_str:
        genome_folder = Path(genome_folder_str)
    else:
        genome_folder = config_path.parent

    # Parse genome servers
    servers = raw.get("genome_servers", [])
    if servers is None:
        servers = []
    elif isinstance(servers, str):
        servers = [servers]

    # Parse genomes
    raw_genomes = raw.get("genomes", {})
    if raw_genomes is None:
        raw_genomes = {}

    genomes = []
    for key, genome_data in raw_genomes.items():
        is_digest_key = _is_hex_digest(key)
        genomes.append(_parse_genome(key, genome_data, is_digest_key))

    # Deduplicate v0.3 genomes
    if config_version < 0.4:
        genomes = _deduplicate_v03_genomes(genomes)

    return LegacyConfig(
        config_version=config_version,
        genome_folder=genome_folder,
        genome_servers=servers,
        genomes=genomes,
    )
