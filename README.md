# refgenie-upgrade

Migrate legacy refgenie installations (v0.3/v0.4) to refgenie1. Reads the
legacy `genome_config.yaml`, resolves genome digests to GA4GH format, moves
asset files into the new layout, and registers everything in a fresh refgenie1
database.

## Installation

Install from GitHub (it is not on PyPI):

```bash
pip install git+https://github.com/refgenie/refgenie-upgrade.git
```

Or with uv:

```bash
uv pip install git+https://github.com/refgenie/refgenie-upgrade.git
```

If refgenie 1.0 is not installed yet, this installs it too. You do not need `--pre`.

## Usage

### Basic migration

```bash
refgenie-upgrade /path/to/genome_config.yaml
```

Or using the `REFGENIE` environment variable:

```bash
export REFGENIE=/path/to/genome_config.yaml
refgenie-upgrade
```

### Dry run

See what would be migrated without changing anything:

```bash
refgenie-upgrade genome_config.yaml --dry-run
```

### Target directory

By default, the new refgenie1 instance is created alongside the legacy data.
Specify a different target:

```bash
refgenie-upgrade genome_config.yaml --target-dir /data/refgenie1
```

### Transfer modes

Choose how asset files are transferred to the new layout:

```bash
refgenie-upgrade genome_config.yaml --symlink   # Default: symlink to originals
refgenie-upgrade genome_config.yaml --copy      # Copy files (doubles disk usage)
refgenie-upgrade genome_config.yaml --move      # Move files (frees legacy space)
```

## What gets migrated

- **Genomes** with GA4GH-format digests
- **Aliases** (human-readable genome names)
- **Assets** (fasta, bowtie2_index, bwa_index, etc.) with content-addressed directories
- **Seek keys** (file paths within assets)

## What does not get migrated

- Build logs and build recipes
- Archive configurations
- Server configurations
- Download statistics

## Limitations

- Genomes not in the built-in lookup table require a FASTA file on disk to
  compute the GA4GH digest. If neither is available, the genome is skipped.
- Assets with absolute paths (symlinked child assets) are skipped.
- Legacy asset digests (MD5) are not preserved; content digests are recomputed
  using SHA-256.
