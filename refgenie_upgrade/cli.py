"""Command-line interface for refgenie-upgrade."""

import argparse
import os
import sys
from pathlib import Path

from rich.console import Console

from refgenie_upgrade.file_mover import TransferMode
from refgenie_upgrade.migrator import MigrationResult, migrate

console = Console()


def _print_summary(result: MigrationResult, dry_run: bool = False) -> None:
    """Print a summary of the migration result."""
    console.print()
    action = "would be" if dry_run else "were"

    if result.genomes_migrated or result.assets_migrated:
        console.print(
            f"[bold green]Summary:[/bold green] "
            f"{result.genomes_migrated} genome(s) ({result.assets_migrated} asset(s)) "
            f"{action} migrated"
        )

    if result.genomes_skipped:
        console.print(
            f"[yellow]{result.genomes_skipped} genome(s) skipped[/yellow]"
        )

    if result.assets_skipped:
        console.print(
            f"[yellow]{result.assets_skipped} asset(s) skipped[/yellow]"
        )

    if result.warnings:
        console.print()
        console.print("[bold yellow]Warnings:[/bold yellow]")
        for warning in result.warnings:
            console.print(f"  {warning}")

    if result.errors:
        console.print()
        console.print("[bold red]Errors:[/bold red]")
        for error in result.errors:
            console.print(f"  {error}")

    # On a real run that produced an instance, tell the user exactly how to
    # point refgenie at it -- otherwise the obvious next command opens a new,
    # empty default instance instead.
    if not dry_run and result.home_dir is not None:
        console.print()
        console.print("[bold]Point refgenie at the migrated instance:[/bold]")
        console.print(f"  export REFGENIE_HOME_PATH={result.home_dir}")
        console.print("[dim]  # or, equivalently:[/dim]")
        console.print(f"[dim]  export REFGENIE_DB_CONFIG_PATH={result.db_config_path}[/dim]")
        console.print(f"[dim]  export REFGENIE_GENOME_FOLDER={result.genome_folder}[/dim]")


def main():
    parser = argparse.ArgumentParser(
        prog="refgenie-upgrade",
        description="Migrate a legacy refgenie installation to refgenie1.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=None,
        help="Path to legacy genome_config.yaml. Falls back to REFGENIE env var.",
    )
    parser.add_argument(
        "--genome-folder",
        type=Path,
        default=None,
        help="Override the genome_folder from the config.",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=None,
        help="Target directory for the new refgenie1 instance.",
    )
    transfer = parser.add_mutually_exclusive_group()
    transfer.add_argument(
        "--copy",
        action="store_const",
        const=TransferMode.COPY,
        dest="mode",
        help="Copy asset files to the new location.",
    )
    transfer.add_argument(
        "--move",
        action="store_const",
        const=TransferMode.MOVE,
        dest="mode",
        help="Move asset files to the new location.",
    )
    transfer.add_argument(
        "--symlink",
        action="store_const",
        const=TransferMode.SYMLINK,
        dest="mode",
        help="Symlink asset files to the new location (default).",
    )
    parser.set_defaults(mode=TransferMode.SYMLINK)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without touching anything.",
    )

    args = parser.parse_args()

    config_path = args.config
    if config_path is None:
        env_val = os.environ.get("REFGENIE")
        if env_val is not None:
            config_path = Path(env_val)

    if config_path is None:
        parser.error("Provide config path or set REFGENIE env var.")

    config_path = Path(config_path)
    if not config_path.exists():
        console.print(f"[red]Config file not found: {config_path}[/red]")
        sys.exit(1)

    result = migrate(
        config_path=config_path,
        target_dir=args.target_dir,
        genome_folder_override=args.genome_folder,
        transfer_mode=args.mode,
        dry_run=args.dry_run,
    )

    _print_summary(result, dry_run=args.dry_run)
    sys.exit(1 if result.errors else 0)


if __name__ == "__main__":
    main()
