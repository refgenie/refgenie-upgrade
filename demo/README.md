# Upgrade demo

`run_demo.sh` walks the whole upgrade path a legacy user would take, using real
servers and small genomes (rCRSd and mouse_chrM2x, under 20 MB in total):

1. **Legacy refgenie.** Installs refgenie 0.x and pulls `rCRSd/fasta`,
   `rCRSd/bowtie2_index` and `mouse_chrM2x/fasta` from the legacy server,
   refgenomes.databio.org.
2. **Upgrade.** Installs refgenie 1.0 and this repo's `refgenie-upgrade`, then
   migrates that legacy folder into a new refgenie 1.0 instance.
3. **New server.** Points the migrated instance at api.refgenie.org and checks
   that it works:
   - each migrated asset can still be found with `refgenie seek`
   - `refgenie listr` can read the server
   - the server knows each migrated genome by its new digest
   - each migrated fasta has the same digest as the server's fasta (same bytes,
     so it should be the same asset)
   - new assets (`rCRSd/fasta_index`, `mouse_chrM2x/bowtie2_index`) can be
     pulled from the server onto the migrated genomes

Each check prints PASS or FAIL. The script exits non-zero if any check fails.

## Run it

Needs `uv` and `curl`. It takes about a minute.

```bash
bash demo/run_demo.sh ~/work/upgrade-demo
```

Without a folder argument it uses a new temporary folder. Nothing outside the
work folder is touched, and your own `REFGENIE*` settings are ignored. Logs for
every step are in `<work folder>/logs/`. Delete the work folder when done.

## Settings

Set these as environment variables to test other versions:

| Variable | Default | What it is |
| --- | --- | --- |
| `LEGACY_SPEC` | `refgenie<1` | Legacy refgenie to install |
| `REFGENIE_SPEC` | `refgenie>=1.0.0a1` | refgenie 1.0 to install |
| `UPGRADE_SPEC` | this repo | refgenie-upgrade to install |
| `SERVER` | `https://api.refgenie.org` | New server to test against |
| `UPGRADE_MODE` | `--symlink` | `--symlink`, `--copy` or `--move` |
| `PYTHON` | `3.11` | Python version for both environments |

For example, to test against a local refgenie checkout:

```bash
REFGENIE_SPEC=../refgenie1 bash demo/run_demo.sh ~/work/upgrade-demo
```
