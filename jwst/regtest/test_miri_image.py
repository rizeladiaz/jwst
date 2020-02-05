import pytest
from astropy.io.fits.diff import FITSDiff
from numpy.testing import assert_allclose
from jwst.pipeline.collect_pipeline_cfgs import collect_pipeline_cfgs
from gwcs.wcstools import grid_from_bounding_box
from jwst.stpipe import Step
from jwst import datamodels

@pytest.fixture(scope="module")
def run_pipelines(jail, rtdata_module):
    """Run stage 1-3 pipelines on MIRI imaging data."""
    rtdata = rtdata_module
    rtdata.get_data("miri/image/det_image_1_MIRIMAGE_F770Wexp1_5stars_uncal.fits")

    collect_pipeline_cfgs("config")

    # Run detector1 pipeline only on one of the _uncal files
    args = ["config/calwebb_detector1.cfg", rtdata.input,
        "--save_calibrated_ramp=True",
        "--steps.dq_init.save_results=True",
        "--steps.saturation.save_results=True",
        "--steps.refpix.save_results=True",
        "--steps.rscd.save_results=True",
        "--steps.lastframe.save_results=True",
        "--steps.firstframe.save_results=True",
        "--steps.linearity.save_results=True",
        "--steps.dark_current.save_results=True",
        "--steps.jump.rejection_threshold=10.0",
        ]
    Step.from_cmdline(args)

    # Now run image2 pipeline on the _rate file, saving intermediate products
    rtdata.input = 'det_image_1_MIRIMAGE_F770Wexp1_5stars_rate.fits'
    args = ["config/calwebb_image2.cfg", rtdata.input,
        "--steps.assign_wcs.save_results=True",
        "--steps.flat_field.save_results=True"
        ]
    Step.from_cmdline(args)

    # Grab rest of _rate files for the asn and run image2 pipeline on each to
    # produce fresh _cal files for the image3 pipeline.  We won't check these
    # or look at intermediate products, and skip resample (don't need i2d image)
    rate_files = [
    "miri/image/det_image_1_MIRIMAGE_F770Wexp2_5stars_rate.fits",
    "miri/image/det_image_2_MIRIMAGE_F770Wexp1_5stars_rate.fits",
    "miri/image/det_image_2_MIRIMAGE_F770Wexp2_5stars_rate.fits",
    ]
    for rate_file in rate_files:
        rtdata.get_data(rate_file)
        args = ["config/calwebb_image2.cfg", rtdata.input,
            "--steps.resample.skip=True"]
        Step.from_cmdline(args)

    # Get the level3 assocation json file (though not its members) and run
    # image3 pipeline on all _cal files listed in association
    rtdata.get_data("miri/image/det_dithered_5stars_image3_asn.json")
    args = ["config/calwebb_image3.cfg", rtdata.input,
        # Set some unique param values needed for these data
        "--steps.tweakreg.snr_threshold=200",
        "--steps.tweakreg.use2dhist=False",
        "--steps.source_catalog.snr_threshold=20",
        ]
    Step.from_cmdline(args)

    return rtdata


@pytest.mark.bigdata
@pytest.mark.parametrize("suffix", ["dq_init", "saturation", "refpix", "rscd",
    "firstframe", "lastframe", "linearity", "dark_current", "ramp", "rate",
    "rateints",
    "assign_wcs", "flat_field", "cal", "i2d",
    "a3001_crf"])
def test_miri_image_stages123(run_pipelines, fitsdiff_default_kwargs, suffix):
    """Regression test of detector1 and image2 pipelines performed on MIRI data."""
    rtdata = run_pipelines
    rtdata.input = "det_image_1_MIRIMAGE_F770Wexp1_5stars_uncal.fits"
    output = "det_image_1_MIRIMAGE_F770Wexp1_5stars_" + suffix + ".fits"
    rtdata.output = output

    rtdata.get_truth("truth/test_miri_image_stages/" + output)

    # Set tolerances so the crf, rscd and rateints file comparisons work across
    # architectures
    fitsdiff_default_kwargs["rtol"] = 1e-4
    fitsdiff_default_kwargs["atol"] = 1e-4
    diff = FITSDiff(rtdata.output, rtdata.truth, **fitsdiff_default_kwargs)
    assert diff.identical, diff.report()


@pytest.mark.bigdata
def test_miri_image_stage3_i2d(run_pipelines, fitsdiff_default_kwargs):
    rtdata = run_pipelines
    rtdata.input = "det_dithered_5stars_image3_asn.json"
    rtdata.output = "det_dithered_5stars_f770w_i2d.fits"
    rtdata.get_truth("truth/test_miri_image_stages/det_dithered_5stars_f770w_i2d.fits")

    fitsdiff_default_kwargs["rtol"] = 1e-4
    diff = FITSDiff(rtdata.output, rtdata.truth, **fitsdiff_default_kwargs)
    assert diff.identical, diff.report()


@pytest.mark.bigdata
def test_miri_image_stage3_catalog(run_pipelines, diff_astropy_tables):
    rtdata = run_pipelines
    rtdata.input = "det_dithered_5stars_image3_asn.json"
    rtdata.output = "det_dithered_5stars_f770w_cat.ecsv"
    rtdata.get_truth("truth/test_miri_image_stages/det_dithered_5stars_f770w_cat.ecsv")

    diff = diff_astropy_tables(rtdata.output, rtdata.truth, rtol=1e-4)
    assert len(diff) == 0, "\n".join(diff)


@pytest.mark.bigdata
def test_miri_image_wcs(run_pipelines, fitsdiff_default_kwargs):
    rtdata = run_pipelines

    # get input assign_wcs and truth file
    output = "det_image_1_MIRIMAGE_F770Wexp1_5stars_assign_wcs.fits"
    rtdata.output = output
    rtdata.get_truth("truth/test_miri_image_stages/" + output)
    # Open the output and truth file
    im = datamodels.open(output)
    im_truth = datamodels.open(rtdata.truth)

    x, y = grid_from_bounding_box(im.meta.wcs.bounding_box)
    ra, dec = im.meta.wcs(x, y)
    ratruth, dectruth = im_truth.meta.wcs(x, y)
    assert_allclose(ra, ratruth)
    assert_allclose(dec, dectruth)

    # Test the inverse transform
    xtest, ytest = im.meta.wcs.backward_transform(ra, dec)
    xtruth, ytruth = im_truth.meta.wcs.backward_transform (ratruth, dectruth)
    assert_allclose(xtest, xtruth)
    assert_allclose(ytest, ytruth)
