"""Orchestrate the full migration from legacy refgenie to refgenie1.

Composes the config parser, digest resolver, and file mover to perform
a one-way migration of genomes, aliases, and assets into a new refgenie1
instance.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from refgenie_upgrade.config_parser import LegacyConfig, LegacyGenome, parse_legacy_config
from refgenie_upgrade.digest_resolver import _find_fasta_file, resolve_genome_digest
from refgenie_upgrade.file_mover import (
    FileTransferPlan,
    TransferMode,
    content_digest,
    execute_transfer,
    plan_asset_transfer,
    resolve_legacy_asset_dir,
)

console = Console()


@dataclass
class MigrationResult:
    genomes_migrated: int = 0
    genomes_skipped: int = 0
    assets_migrated: int = 0
    assets_skipped: int = 0
    skipped_reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    transfer_plans: list[FileTransferPlan] = field(default_factory=list)
    # Resolved layout of the produced instance (set on a real, non-dry run) so
    # the CLI can print the exact env vars to point refgenie at it.
    home_dir: Path | None = None
    genome_folder: Path | None = None
    db_config_path: Path | None = None


def _init_refgenie1(target_dir: Path, db_path: Path | None = None):
    """Initialize a refgenie1 instance at the target directory.

    ``target_dir`` is treated as the refgenie *home*: it is laid out to match
    the native refgenie1 defaults so the produced instance is discoverable via
    ``REFGENIE_HOME_PATH`` (or the explicit db-config / genome-folder pair):

        <target>/genomes                    -- genome folder (assets live here)
        <target>/refgenie_db_config.yaml    -- database config
        <target>/refgenie.db                -- sqlite database

    Returns:
        tuple: (Refgenie instance, genome_folder, db_config_path).
    """
    from refgenie.config import config as refgenie_config
    from refgenie.config.db import SQLiteConfig, dump_db_config
    from refgenie import Refgenie

    target_dir.mkdir(parents=True, exist_ok=True)
    genome_folder = target_dir / "genomes"
    genome_folder.mkdir(parents=True, exist_ok=True)

    # Set up the database config for SQLite at the target
    if db_path is None:
        db_path = target_dir / "refgenie.db"
    db_config_path = target_dir / "refgenie_db_config.yaml"

    if not db_config_path.exists():
        # SQLiteConfig.url is a read-only computed field derived from .path, so
        # build the config with the path rather than assigning to url.
        db_cfg = SQLiteConfig(path=str(db_path))
        db_config_path.write_text(dump_db_config(db_cfg))

    # Point refgenie config at our target
    refgenie_config.genome_folder = genome_folder
    refgenie_config.database_config_path = str(db_config_path)

    rgc = Refgenie(
        database_config_path=db_config_path,
        suppress_migrations=True,
    )
    rgc.database.init(genome_folder=genome_folder)
    return rgc, genome_folder, db_config_path


def _ensure_asset_class(rgc, asset_name: str) -> None:
    """Ensure an asset class exists for the given asset name.

    If refgenie1 does not have an asset class registered for this legacy
    asset type, register a minimal generic one.
    """
    try:
        rgc.asset_class.get(asset_name)
        return  # Already exists
    except Exception:
        pass

    # Register a minimal asset class via the manager's direct DB interface
    from refgenie.db.tables import AssetClass

    ac = AssetClass(
        name=asset_name,
        version="0.1.0",
        description=f"Legacy asset class for '{asset_name}' (migrated from refgenie v0)",
        serving_modes=["archive"],
    )
    with rgc.database._database_session as session:
        session.add(ac)
        session.commit()


def _migrate_genome(
    rgc,
    genome: LegacyGenome,
    legacy_config: LegacyConfig,
    genome_folder: Path,
    transfer_mode: TransferMode,
    dry_run: bool,
    result: MigrationResult,
) -> bool:
    """Migrate a single genome and its assets.

    Returns True if the genome was migrated, False if skipped.
    """
    # Resolve digest
    resolution = resolve_genome_digest(
        legacy_hex=genome.digest,
        genome_folder=legacy_config.genome_folder,
        aliases=genome.aliases,
    )

    alias_display = ", ".join(genome.aliases) if genome.aliases else genome.digest[:12]

    if resolution.ga4gh_digest is None:
        reason = (
            f"Genome {alias_display} ({genome.digest}): skipped -- "
            f"cannot resolve GA4GH digest. Provide the FASTA file at "
            f"{legacy_config.genome_folder}/data/{genome.digest}/fasta/default/ "
            f"or use a config with known genomes."
        )
        result.skipped_reasons.append(reason)
        result.genomes_skipped += 1
        return False

    ga4gh_digest = resolution.ga4gh_digest

    # Locate the genome's FASTA on disk. In local mode aliases and seek are
    # store-owned, so the sequence collection must be loaded into the RefgetStore
    # for anything to resolve -- a DB-only genome row is not enough.
    fasta_path = _find_fasta_file(legacy_config.genome_folder, genome.digest)

    if dry_run:
        console.print(
            f"  {alias_display} ({genome.digest[:12]}...) -> "
            f"{ga4gh_digest} [{resolution.method}]"
        )
        if fasta_path is None:
            console.print(
                f"    [yellow]no FASTA on disk; local aliases/seek would not "
                f"resolve without it[/yellow]"
            )

    if not dry_run:
        if fasta_path is not None:
            # Same entry point as `genome init --fasta`: imports the FASTA into
            # the store (loading the collection so StoreAliasManager resolves),
            # inserts the genome row, and repairs aliases when it already exists.
            try:
                digest_out, _created = rgc.genome.initialize_genome(
                    fasta_file_path=fasta_path,
                    description=genome.description or "",
                    alias_names=genome.aliases,
                    use_existing=True,
                )
            except Exception as e:
                result.errors.append(
                    f"Genome {alias_display}: FASTA import failed: {e}"
                )
                result.genomes_skipped += 1
                return False

            # The store-computed digest must match the migrator's resolved
            # digest, or assets would be registered under a divergent genome.
            if digest_out != ga4gh_digest:
                result.errors.append(
                    f"Genome {alias_display}: resolved GA4GH digest {ga4gh_digest} "
                    f"does not match store-computed digest {digest_out}; skipping."
                )
                result.genomes_skipped += 1
                return False
        else:
            # Fallback: no FASTA on disk (digest came from the lookup table).
            # Register the genome row, but local aliases/seek will not resolve.
            try:
                rgc.genome.add(
                    digest=ga4gh_digest,
                    description=genome.description or "",
                    alias_names=genome.aliases,
                )
            except Exception as e:
                if "UNIQUE constraint" in str(e) or "already exists" in str(e).lower():
                    for alias in genome.aliases:
                        try:
                            rgc.alias.add(alias, ga4gh_digest)
                        except Exception:
                            pass
                else:
                    result.errors.append(
                        f"Failed to register genome {alias_display}: {e}"
                    )
                    result.genomes_skipped += 1
                    return False
            warning = (
                f"Genome {alias_display}: no FASTA found on disk; registered the "
                f"genome row only. Local aliases and seek will NOT resolve until "
                f"the FASTA is imported."
            )
            result.warnings.append(warning)
            console.print(f"  [yellow]{warning}[/yellow]")

    # Migrate each asset
    for asset in genome.assets:
        for tag in asset.tags:
            _migrate_asset_tag(
                rgc=rgc,
                genome=genome,
                legacy_config=legacy_config,
                ga4gh_digest=ga4gh_digest,
                asset_name=asset.name,
                tag=tag,
                is_default_tag=(tag.name == asset.default_tag),
                genome_folder=genome_folder,
                transfer_mode=transfer_mode,
                dry_run=dry_run,
                result=result,
            )

    # Render the name-addressed alias tree from the registered assetname rows,
    # exactly as `alias set` does. Must run AFTER assets are added, since it
    # walks those rows. Only meaningful when the FASTA import loaded the store.
    if not dry_run and fasta_path is not None and genome.aliases:
        try:
            from refgenie.models import GenomeAlias, GenomeDigest

            rgc.asset.tree.render_genome(
                GenomeDigest(ga4gh_digest), aliases=[GenomeAlias(a) for a in genome.aliases]
            )
        except Exception as e:
            result.errors.append(
                f"Genome {alias_display}: alias-tree render failed: {e}"
            )

    result.genomes_migrated += 1
    return True


#: Legacy bookkeeping that must not leak into the content or alias tree; the
#: native refgenie1 layout carries neither. "_refgenie_build" is the legacy
#: build-log directory. "*.rgsi" is the sequence-collection index legacy
#: refgenconf writes into a pulled fasta asset; refgenie1 keeps that in its
#: RefgetStore instead, and a fasta carrying it would not match the server's.
_LEGACY_EXCLUDE = ["_refgenie_build", "*.rgsi"]


def _infer_seek_key_type(content_dir: Path, value: str):
    """Infer the refgenie1 SeekKeyType for a legacy seek-key value.

    Legacy configs store no explicit seek-key type. refgenie1 needs one so that
    ``seek`` returns a filesystem path (file/directory/prefix) rather than the
    raw string. The type is inferred from what the transferred content actually
    contains:

    - ``.``                         -> directory (the asset root)
    - value names an existing file  -> file  (e.g. ``<ga4gh>.fa``)
    - value names an existing dir   -> directory
    - files share it as a stem/pfx  -> prefix (e.g. bowtie2 ``<ga4gh>`` -> ``<ga4gh>.1.bt2``)
    - otherwise                     -> string (non-path, returned verbatim)

    Returns a ``SeekKeyType`` enum value.
    """
    from refgenie.db.tables import SeekKeyType

    if value == ".":
        return SeekKeyType.directory
    target = content_dir / value
    if target.is_file():
        return SeekKeyType.file
    if target.is_dir():
        return SeekKeyType.directory
    try:
        for child in content_dir.iterdir():
            if child.name != value and child.name.startswith(value):
                return SeekKeyType.prefix
    except OSError:
        pass
    return SeekKeyType.string


def _migrate_asset_tag(
    rgc,
    genome,
    legacy_config,
    ga4gh_digest,
    asset_name,
    tag,
    is_default_tag,
    genome_folder,
    transfer_mode,
    dry_run,
    result,
):
    """Migrate a single asset tag."""
    alias_display = ", ".join(genome.aliases) if genome.aliases else genome.digest[:12]

    # Check if asset_path is absolute (symlinked/child asset)
    if os.path.isabs(tag.asset_path):
        # This is a child asset pointing to a parent. Skip with a note.
        result.assets_skipped += 1
        result.skipped_reasons.append(
            f"Asset {alias_display}/{asset_name}:{tag.name}: skipped -- "
            f"absolute asset_path (symlinked child asset): {tag.asset_path}"
        )
        return

    # Find the source directory on disk
    source_dir = resolve_legacy_asset_dir(
        genome_folder=legacy_config.genome_folder,
        hex_digest=genome.digest,
        asset_name=asset_name,
        tag_name=tag.name,
        asset_path=tag.asset_path,
    )

    if source_dir is None or not source_dir.exists():
        result.assets_skipped += 1
        result.skipped_reasons.append(
            f"Asset {alias_display}/{asset_name}:{tag.name}: skipped -- "
            f"source directory not found on disk"
        )
        return

    # Rewrite legacy-hex-stemmed content filenames to the GA4GH digest stem so
    # the rendered alias tree matches native (`create_alias_symlinks` rewrites
    # <ga4gh> -> <alias>, and native names content files <ga4gh>.fa). Migrated
    # files keep their legacy-hex stems otherwise, which contain no GA4GH digest
    # and are never rewritten. The seek-key values are rewritten the same way.
    legacy_hex = genome.digest
    rename_map = {}
    for child in source_dir.iterdir():
        if child.is_file() and child.name.startswith(legacy_hex):
            rename_map[child.name] = ga4gh_digest + child.name[len(legacy_hex):]

    # Digest the files as they will land (renamed, legacy bookkeeping dropped),
    # not the legacy folder: the digest covers file names, so only this matches
    # what refgenie1, and the server, compute for the same content.
    try:
        digest = content_digest(source_dir, rename_map, _LEGACY_EXCLUDE)
    except Exception as e:
        result.assets_skipped += 1
        result.skipped_reasons.append(
            f"Asset {alias_display}/{asset_name}:{tag.name}: skipped -- "
            f"could not compute content digest: {e}"
        )
        return

    dest_dir = genome_folder / "data" / ga4gh_digest / asset_name / digest
    plan = plan_asset_transfer(
        source_dir,
        dest_dir,
        transfer_mode,
        rename_map=rename_map,
        exclude=_LEGACY_EXCLUDE,
    )
    result.transfer_plans.append(plan)

    if dry_run:
        console.print(
            f"    {asset_name} ({tag.name}): "
            f"data/.../{asset_name}/{digest[:12]}... "
            f"<- {source_dir}"
        )
        result.assets_migrated += 1
        return

    # Execute the transfer
    transfer_result = execute_transfer(plan)
    if not transfer_result.success:
        result.assets_skipped += 1
        result.errors.append(
            f"Asset {alias_display}/{asset_name}:{tag.name}: "
            f"transfer failed: {transfer_result.error}"
        )
        return

    # Ensure asset class exists
    _ensure_asset_class(rgc, asset_name)

    # Build custom seek keys dict from legacy seek keys, rewriting the legacy-hex
    # stem to the GA4GH digest to match the renamed content files, and inferring
    # a proper path type from the transferred content so seek returns a file path
    # rather than the bare string.
    custom_seek_keys = {}
    for sk in tag.seek_keys:
        value = sk.value.replace(legacy_hex, ga4gh_digest)
        custom_seek_keys[sk.name] = (value, _infer_seek_key_type(dest_dir, value))

    # Register the asset in refgenie1
    try:
        # The path must be relative to the genome folder
        rel_path = dest_dir.relative_to(genome_folder)
        from refgenie.models import GenomeDigest

        rgc.asset.content.add(
            asset_class_name=asset_name,
            path=rel_path,
            asset_group_name=asset_name,
            genome_digest=GenomeDigest(ga4gh_digest),
            asset_name=tag.name,
            description=f"Migrated from legacy refgenie",
            custom_seek_keys=custom_seek_keys if custom_seek_keys else None,
            digest=digest,
            set_default=is_default_tag,
        )
        result.assets_migrated += 1
    except Exception as e:
        result.errors.append(
            f"Asset {alias_display}/{asset_name}:{tag.name}: "
            f"registration failed: {e}"
        )
        result.assets_skipped += 1


def migrate(
    config_path: Path,
    target_dir: Path | None = None,
    genome_folder_override: Path | None = None,
    transfer_mode: TransferMode = TransferMode.SYMLINK,
    dry_run: bool = False,
) -> MigrationResult:
    """Run the full migration from legacy refgenie to refgenie1.

    Steps:
    1. Parse legacy config
    2. Resolve target directory (--target-dir or in-place)
    3. Initialize refgenie1 instance at target
    4. For each genome:
       a. Resolve legacy hex digest to GA4GH digest
       b. Register genome in refgenie1 DB
       c. Register aliases
       d. For each asset in the genome:
          i.   Compute content digest of the asset directory
          ii.  Plan file transfer (move/copy/symlink)
          iii. Execute transfer (unless dry_run)
          iv.  Register asset in DB

    Args:
        config_path: Path to the legacy genome_config.yaml.
        target_dir: Target directory for the new refgenie1 instance.
            If None, creates a new instance alongside the legacy one.
        genome_folder_override: Override the genome_folder from the config.
        transfer_mode: How to transfer files (copy, move, or symlink).
        dry_run: If True, show what would be done without touching anything.

    Returns:
        MigrationResult with counts and any error messages.
    """
    result = MigrationResult()

    # Step 1: Parse legacy config
    try:
        legacy_config = parse_legacy_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        result.errors.append(f"Failed to parse config: {e}")
        return result

    # Override genome_folder if specified
    if genome_folder_override:
        legacy_config.genome_folder = genome_folder_override

    # Step 2: Resolve target directory
    if target_dir is None:
        target_dir = legacy_config.genome_folder.parent / "refgenie1_data"

    target_dir = target_dir.resolve()

    if dry_run:
        console.print()
        console.print("[bold]refgenie-upgrade dry run[/bold]")
        console.print("=" * 40)
        console.print()
        console.print(f"Source: {config_path} (v{legacy_config.config_version})")
        console.print(f"Genome folder: {legacy_config.genome_folder}")
        console.print(f"Target: {target_dir}")
        console.print(f"Transfer mode: {transfer_mode.value}")
        console.print()
        console.print("[bold]Genomes to migrate:[/bold]")
    else:
        console.print(f"Migrating from {config_path} to {target_dir}")
        console.print(f"Transfer mode: {transfer_mode.value}")

    # Step 3: Initialize refgenie1 (skip for dry run). target_dir is the home;
    # assets live under <target>/genomes.
    rgc = None
    genome_folder = target_dir / "genomes"
    if not dry_run:
        try:
            rgc, genome_folder, db_config_path = _init_refgenie1(target_dir)
        except Exception as e:
            result.errors.append(f"Failed to initialize refgenie1: {e}")
            return result
        result.home_dir = target_dir
        result.genome_folder = genome_folder
        result.db_config_path = db_config_path

    # Step 4: Migrate each genome
    for genome in legacy_config.genomes:
        _migrate_genome(
            rgc=rgc,
            genome=genome,
            legacy_config=legacy_config,
            genome_folder=genome_folder,
            transfer_mode=transfer_mode,
            dry_run=dry_run,
            result=result,
        )

    # Print skipped items
    if dry_run and result.skipped_reasons:
        console.print()
        console.print("[bold]Skipped:[/bold]")
        for reason in result.skipped_reasons:
            console.print(f"  {reason}")

    return result
