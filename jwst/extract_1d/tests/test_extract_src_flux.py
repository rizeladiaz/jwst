"""
Test for extract_1d._extract_src_flux
"""
import math

import numpy as np

from jwst.extract_1d import extract1d

def test_extract_src_flux():

    shape = (9, 5)
    image = np.arange(shape[0] * shape[1], dtype=np.float32).reshape(shape)
    x = 2
    j = 2
    lam = 1.234                 # an arbitrary value (not actually used)
    weights = None
    bkgmodel = None
    lower = np.zeros(shape[1], dtype=np.float64) + 3.   # middle of pixel 3
    upper = np.zeros(shape[1], dtype=np.float64) + 7.   # middle of pixel 7
    srclim = [[lower, upper]]

    (total_flux, bkg_flux, tarea, twht) = extract1d._extract_src_flux(
                    image, x, j, lam, srclim, weights, bkgmodel)

    # 0.5 * 17. + 22. + 27. + 32. + 0.5 * 37.
    assert math.isclose(total_flux, 108., rel_tol=1.e-8, abs_tol=1.e-8)

    assert bkg_flux == 0.

    assert math.isclose(tarea, 4., rel_tol=1.e-8, abs_tol=1.e-8)

    image[5, 2] = np.nan

    (total_flux, bkg_flux, tarea, twht) = extract1d._extract_src_flux(
                    image, x, j, lam, srclim, weights, bkgmodel)

    # 0.5 * 17. + 22. + 32. + 0.5 * 37.
    assert math.isclose(total_flux, 81., rel_tol=1.e-8, abs_tol=1.e-8)

    assert math.isclose(tarea, 3., rel_tol=1.e-8, abs_tol=1.e-8)

    image[:, 2] = np.nan

    (total_flux, bkg_flux, tarea, twht) = extract1d._extract_src_flux(
                    image, x, j, lam, srclim, weights, bkgmodel)

    assert np.isnan(total_flux)

    assert tarea == 0.
