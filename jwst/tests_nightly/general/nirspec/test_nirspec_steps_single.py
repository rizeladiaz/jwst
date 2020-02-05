import pytest
import numpy as np

from numpy.testing import assert_allclose
from gwcs.wcstools import grid_from_bounding_box
from jwst.tests.base_classes import BaseJWSTTest, raw_from_asn
from jwst.assign_wcs import AssignWcsStep, nirspec
from jwst.datamodels import ImageModel
from jwst.pipeline import Detector1Pipeline, Spec2Pipeline
from jwst.pipeline.collect_pipeline_cfgs import collect_pipeline_cfgs
from jwst.imprint import ImprintStep
from jwst.ramp_fitting import RampFitStep
from jwst.master_background import MasterBackgroundStep
from jwst import datamodels


@pytest.mark.bigdata
class TestDetector1Pipeline(BaseJWSTTest):
    input_loc = 'nirspec'
    ref_loc = ['test_pipelines', 'truth']
    test_dir = 'test_pipelines'

    def test_detector1pipeline4(self):
        """

        Regression test of calwebb_detector1 pipeline performed on NIRSpec data.

        """
        input_file = self.get_data(self.test_dir,
                                   'jw84600007001_02101_00001_nrs1_uncal.fits')
        step = Detector1Pipeline()
        step.save_calibrated_ramp = True
        step.ipc.skip = True
        step.persistence.skip = True
        step.jump.rejection_threshold = 4.0
        step.ramp_fit.save_opt = False
        step.output_file = 'jw84600007001_02101_00001_nrs1_rate.fits'
        step.run(input_file)

        outputs = [('jw84600007001_02101_00001_nrs1_ramp.fits',
                    'jw84600007001_02101_00001_nrs1_ramp_ref.fits'),
                   ('jw84600007001_02101_00001_nrs1_rate.fits',
                    'jw84600007001_02101_00001_nrs1_rate_ref.fits')
                  ]
        self.compare_outputs(outputs)


@pytest.mark.bigdata
class TestNIRSpecImprint(BaseJWSTTest):
    input_loc = 'nirspec'
    ref_loc = ['test_imprint', 'truth']
    test_dir = 'test_imprint'

    def test_imprint_nirspec(self):
        """

        Regression test of imprint step performed on NIRSpec MSA data.

        """
        input_file = self.get_data(self.test_dir,
                                   'jw00038001001_01101_00001_NRS1_rate.fits')
        model_file = self.get_data(self.test_dir,
                                   'NRSMOS-MODEL-21_NRS1_rate.fits')

        result = ImprintStep.call(input_file, model_file, name='imprint')

        output_file = result.meta.filename
        result.save(output_file)
        result.close()

        outputs = [(output_file,
                    'jw00038001001_01101_00001_NRS1_imprint.fits')]
        self.compare_outputs(outputs)


@pytest.mark.bigdata
class TestNIRSpecRampFit(BaseJWSTTest):
    input_loc = 'nirspec'
    ref_loc = ['test_ramp_fit', 'truth']
    test_dir = 'test_ramp_fit'

    def test_ramp_fit_nirspec(self):
        """

        Regression test of ramp_fit step performed on NIRSpec data. This is a single
        integration dataset.

        """
        input_file = self.get_data(self.test_dir,
                                    'jw00023001001_01101_00001_NRS1_jump.fits')

        result, result_int = RampFitStep.call(input_file,
                          save_opt=True,
                          opt_name='rampfit_opt_out.fits', name='RampFit'
                          )
        output_file = result.meta.filename
        result.save(output_file)
        result.close()

        outputs = [(output_file,
                     'jw00023001001_01101_00001_NRS1_ramp_fit.fits'),
                    ('rampfit_opt_out_fitopt.fits',
                     'jw00023001001_01101_00001_NRS1_opt.fits',
                     ['primary','slope','sigslope','yint','sigyint',
                      'pedestal','weights','crmag'])
                  ]
        self.compare_outputs(outputs)


@pytest.mark.bigdata
class TestNIRSpecWCS(BaseJWSTTest):
    input_loc = 'nirspec'
    ref_loc = ['test_wcs', 'nrs1-fs', 'truth']
    test_dir = ['test_wcs', 'nrs1-fs']

    def test_nirspec_nrs1_wcs(self):
        """

        Regression test of creating a WCS object and doing pixel to sky transformation.

        """
        input_file = self.get_data(*self.test_dir,
                                  'jw00023001001_01101_00001_NRS1_ramp_fit.fits')
        ref_file = self.get_data(*self.ref_loc,
                                 'jw00023001001_01101_00001_NRS1_ramp_fit_assign_wcs.fits')

        result = AssignWcsStep.call(input_file, save_results=True, suffix='assign_wcs')
        result.close()

        im = ImageModel(result.meta.filename)
        imref = ImageModel(ref_file)

        for slit in ['S200A1', 'S200A2', 'S400A1', 'S1600A1']:
            w = nirspec.nrs_wcs_set_input(im, slit)
            grid = grid_from_bounding_box(w.bounding_box)
            ra, dec, lam = w(*grid)
            wref = nirspec.nrs_wcs_set_input(imref, slit)
            raref, decref, lamref = wref(*grid)

            assert_allclose(ra, raref, equal_nan=True)
            assert_allclose(dec, decref, equal_nan=True)
            assert_allclose(lam, lamref, equal_nan=True)


@pytest.mark.bigdata
class TestNRSSpec2(BaseJWSTTest):
    input_loc = 'nirspec'
    ref_loc = ['test_pipelines', 'truth']
    test_dir = 'test_pipelines'

    def test_nrs_fs_single_spec2(self):
        """
        Regression test of calwebb_spec2 pipeline performed on NIRSpec fixed-slit data
        that uses a single-slit subarray (S200B1).
        """
        input_file = self.get_data(self.test_dir,
                                   'jw84600002001_02101_00001_nrs2_rate.fits')
        step = Spec2Pipeline()
        step.save_bsub = True
        step.save_results = True
        step.resample_spec.save_results = True
        step.cube_build.save_results = True
        step.extract_1d.save_results = True
        step.run(input_file)

        outputs = [('jw84600002001_02101_00001_nrs2_cal.fits',
                    'jw84600002001_02101_00001_nrs2_cal_ref.fits'),
                   ('jw84600002001_02101_00001_nrs2_s2d.fits',
                    'jw84600002001_02101_00001_nrs2_s2d_ref.fits'),
                   ('jw84600002001_02101_00001_nrs2_x1d.fits',
                    'jw84600002001_02101_00001_nrs2_x1d_ref.fits')
                  ]
        self.compare_outputs(outputs)


@pytest.mark.bigdata
class TestNIRSpecMasterBackground_FS(BaseJWSTTest):
    input_loc = 'nirspec'
    ref_loc = ['test_masterbackground', 'nrs-fs', 'truth']
    test_dir = ['test_masterbackground', 'nrs-fs']

    def test_nirspec_fs_masterbg_user(self):
        """
        Regression test of master background subtraction for NRS FS when a
        user 1-D spectrum is provided.
        """
        # input file has 2-D background image added to it

        input_file = self.get_data(*self.test_dir, 'nrs_sci+bkg_cal.fits')
        # user provided 1-D background was created from the 2-D background image
        input_1dbkg_file = self.get_data(*self.test_dir, 'nrs_bkg_user_clean_x1d.fits')

        result = MasterBackgroundStep.call(input_file,
                                           user_background=input_1dbkg_file,
                                           save_results=True)

        # Compare background-subtracted science data (results)
        # to a truth file. These data are MultiSlitModel data
        result_file = result.meta.filename

        truth_file = self.get_data(*self.ref_loc,
                                  'nrs_sci+bkg_masterbackgroundstep.fits')

        outputs = [(result_file, truth_file)]
        self.compare_outputs(outputs)
        result.close()


@pytest.mark.bigdata
class TestNIRSpecMasterBackground_IFU(BaseJWSTTest):
    input_loc = 'nirspec'
    ref_loc = ['test_masterbackground', 'nrs-ifu', 'truth']
    test_dir = ['test_masterbackground', 'nrs-ifu']

    def test_nirspec_ifu_masterbg_user(self):
        """
        Regression test of master background subtraction for NRS IFU when a
        user 1-D spectrum is provided.
        """
        # input file has 2-D background image added to it
        input_file = self.get_data(*self.test_dir, 'prism_sci_bkg_cal.fits')

        # user-provided 1-D background was created from the 2-D background image
        user_background = self.get_data(*self.test_dir, 'prism_bkg_x1d.fits')

        result = MasterBackgroundStep.call(input_file,
                                           user_background=user_background,
                                           save_results=True)

        # Test 2  compare the science  data with no background
        # to the output from the masterBackground Subtraction step
        # background subtracted science image.
        input_sci_cal_file = self.get_data(*self.test_dir,
                                            'prism_sci_cal.fits')
        input_sci_model = datamodels.open(input_sci_cal_file)

        # We don't want the slices gaps to impact the statisitic
        # loop over the 30 Slices
        for i in range(30):
            slice_wcs = nirspec.nrs_wcs_set_input(input_sci_model, i)
            x, y = grid_from_bounding_box(slice_wcs.bounding_box)
            ra, dec, lam = slice_wcs(x, y)
            valid = np.isfinite(lam)
            result_slice_region = result.data[y.astype(int), x.astype(int)]
            sci_slice_region = input_sci_model.data[y.astype(int),
                                                    x.astype(int)]
            sci_slice = sci_slice_region[valid]
            result_slice = result_slice_region[valid]
            sub = result_slice - sci_slice

            # check for outliers in the science image
            sci_mean = np.nanmean(sci_slice)
            sci_std = np.nanstd(sci_slice)
            upper = sci_mean + sci_std*5.0
            lower = sci_mean - sci_std*5.0
            mask_clean = np.logical_and(sci_slice < upper, sci_slice > lower)

            sub_mean = np.absolute(np.nanmean(sub[mask_clean]))
            atol = 2.0
            assert_allclose(sub_mean, 0, atol=atol)

        # Test 3 Compare background sutracted science data (results)
        #  to a truth file. This data is MultiSlit data

        input_sci_model.close()
        result_file = result.meta.filename
        truth_file = self.get_data(*self.ref_loc,
                                  'prism_sci_bkg_masterbackgroundstep.fits')

        outputs = [(result_file, truth_file)]
        self.compare_outputs(outputs)
        input_sci_model.close()
        result.close()


@pytest.mark.bigdata
class TestNIRSpecMasterBackground_MOS(BaseJWSTTest):
    input_loc = 'nirspec'
    ref_loc = ['test_masterbackground', 'nrs-mos', 'truth']
    test_dir = ['test_masterbackground', 'nrs-mos']

    def test_nirspec_mos_masterbg_user(self):
        """
        Regression test of master background subtraction for NRS MOS when
        a user 1-D spectrum is provided.
        """
        # input file has 2-D background image added to it
        input_file = self.get_data(*self.test_dir, 'nrs_mos_sci+bkg_cal.fits')
        # user provide 1-D background was created from the 2-D background image
        input_1dbkg_file = self.get_data(*self.test_dir, 'nrs_mos_bkg_x1d.fits')

        result = MasterBackgroundStep.call(input_file,
                                           user_background=input_1dbkg_file,
                                           save_results=True)

        # Compare background subtracted science data (results)
        # to a truth file. These data are MultiSlit data.
        result_file = result.meta.filename
        ref_file = self.get_data(*self.ref_loc, 'nrs_mos_sci+bkg_masterbackgroundstep.fits')

        outputs = [(result_file, ref_file)]
        self.compare_outputs(outputs)
        result.close()

@pytest.mark.bigdata
class TestNIRSpecMasterBackgroundNodded(BaseJWSTTest):
    input_loc = 'nirspec'
    ref_loc = ['test_masterbackground', 'nrs-ifu', 'nodded', 'truth']
    test_dir = ['test_masterbackground', 'nrs-ifu', 'nodded']

    rtol = 0.000001

    def test_nirspec_masterbg_nodded(self):
        """Run masterbackground step on NIRSpec association"""
        asn_file = self.get_data(*self.test_dir,
                                  'nirspec_spec3_asn.json')
        for file in raw_from_asn(asn_file):
            self.get_data(*self.test_dir, file)

        collect_pipeline_cfgs('./config')
        result = MasterBackgroundStep.call(
            asn_file,
            config_file='config/master_background.cfg',
            save_background=True,
            save_results=True
            )

        # test 1
        # compare  background subtracted data  to truth files
        # check that the  cal_step master_background ran to complete
        outputs = []
        for model in result:
            assert model.meta.cal_step.master_background == 'COMPLETE'

            result_file = model.meta.filename.replace('cal', 'master_background')
            truth_file = self.get_data(*self.ref_loc, result_file)

            outputs.append((result_file, truth_file))
        self.compare_outputs(outputs)


        # test 2
        # compare the master background combined file to truth file
        master_combined_bkg_file = 'ifu_prism_source_off_fix_NRS1_o001_masterbg.fits'
        truth_background = self.get_data(*self.ref_loc,
                                          master_combined_bkg_file)
        outputs = [(master_combined_bkg_file, truth_background)]
        self.compare_outputs(outputs)
