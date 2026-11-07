"""The implicit legacy ``dir`` seek key is not carried into refgenie1 (#5)."""

from refgenie_upgrade.config_parser import LegacySeekKey
from refgenie_upgrade.migrator import _seek_keys_for_v1

HEX = "94e0d21feb576e6af61cd2a798ad30682ef2428bb7eabbb4"


def _sk(**kw):
    return [LegacySeekKey(name=k, value=v) for k, v in kw.items()]


def test_dir_dropped_when_asset_has_other_keys():
    keys = _seek_keys_for_v1("bowtie2_index", _sk(bowtie2_index=HEX, dir="."))
    assert keys == {"bowtie2_index": HEX}


def test_dir_only_asset_keeps_a_main_key_named_like_the_asset():
    assert _seek_keys_for_v1("my_custom", _sk(dir=".")) == {"my_custom": "."}


def test_other_keys_untouched():
    keys = _seek_keys_for_v1("fasta", _sk(fasta=f"{HEX}.fa", fai=f"{HEX}.fa.fai"))
    assert keys == {"fasta": f"{HEX}.fa", "fai": f"{HEX}.fa.fai"}
