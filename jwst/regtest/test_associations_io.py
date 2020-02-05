from glob import glob
import os

import pytest
from astropy.table import Table

from jwst.associations.tests.helpers import TemporaryDirectory

from jwst.associations import load_asn
from jwst.associations.main import Main


@pytest.mark.slow
@pytest.yield_fixture(
    scope='module',
    params=['yaml', 'json']
)
def make_asns(request, full_pool_rules):
    asn_format = request.param
    pool, rules, pool_fname = full_pool_rules
    with TemporaryDirectory() as path:
        generated = Main([
            pool_fname,
            '-p', path,
            '--save-orphans',
            '--format', asn_format
        ])
        yield generated, path, asn_format


@pytest.mark.slow
def test_roundtrip(make_asns):
    generated, path, asn_format = make_asns
    asn_files = glob(os.path.join(path, '*.' + asn_format))
    assert len(asn_files) == len(generated.associations)

    for asn_file in asn_files:
        with open(asn_file, 'r') as asn_fp:
            load_asn(asn_fp)

    orphaned_files = glob(os.path.join(path, '*.csv'))
    assert len(orphaned_files) == 1
    orphaned = Table.read(
        orphaned_files[0],
        format='ascii',
        delimiter='|'
    )
    assert len(orphaned) == len(generated.orphaned)


@pytest.mark.slow
def test_load_asn_all(make_asns):
    generated, path, asn_format = make_asns
    asn_files = glob(os.path.join(path, '*.' + asn_format))
    assert len(asn_files) == len(generated.associations)

    for asn_file in asn_files:
        with open(asn_file, 'r') as asn_fp:
            asns = load_asn(asn_fp, registry=generated.rules, first=False)
        assert len(asns) > 1
