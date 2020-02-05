"""

Unit tests for saturation flagging

"""

import pytest
import numpy as np

from jwst.saturation import SaturationStep
from jwst.saturation.saturation import do_correction, correct_for_NaN
from jwst.datamodels import RampModel, SaturationModel, dqflags


def test_basic_saturation_flagging(setup_nrc_cube):
    '''Check that the saturation flag is set when a pixel value is above the
       threshold given by the reference file.'''

    # Create inputs, data, and saturation maps
    ngroups = 5
    nrows = 2048
    ncols = 2048
    satvalue = 60000

    data, satmap = setup_nrc_cube(ngroups, nrows, ncols)

    # Add ramp values up to the saturation limit
    data.data[0, 0, 500, 500] = 0
    data.data[0, 1, 500, 500] = 20000
    data.data[0, 2, 500, 500] = 40000
    data.data[0, 3, 500, 500] = 60000   # Signal reaches saturation limit
    data.data[0, 4, 500, 500] = 62000

    # Set saturation value in the saturation model
    satmap.data[500, 500] = satvalue

    # Run the pipeline
    output = do_correction(data, satmap)

    # Make sure that groups with signal > saturation limit get flagged
    satindex = np.argmax(output.data[0, :, 500, 500] == satvalue)
    assert np.all(output.groupdq[0, satindex:, 500, 500] == dqflags.group['SATURATED'])


def test_signal_fluctuation_flagging(setup_nrc_cube):
    '''Check that once a pixel is flagged as saturated in a group, all
       subsequent groups should also be flagged as saturated, even if the
       signal value drops back below saturation.'''

    # Create inputs, data, and saturation maps
    ngroups = 5
    nrows = 2048
    ncols = 2048
    satvalue = 60000

    data, satmap = setup_nrc_cube(ngroups, nrows, ncols)

    # Add ramp values up to the saturation limit
    data.data[0, 0, 500, 500] = 0
    data.data[0, 1, 500, 500] = 20000
    data.data[0, 2, 500, 500] = 40000
    data.data[0, 3, 500, 500] = 60000   # Signal reaches saturation limit
    data.data[0, 4, 500, 500] = 40000   # Signal drops below saturation limit

    # Set saturation value in the saturation model
    satmap.data[500, 500] = satvalue

    # Run the pipeline
    output = do_correction(data, satmap)

    # Make sure that all groups after first saturated group are flagged
    satindex = np.argmax(output.data[0, :, 500, 500] == satvalue)
    assert np.all(output.groupdq[0, satindex:, 500, 500] == dqflags.group['SATURATED'])


def test_all_groups_saturated(setup_nrc_cube):
    '''Check case where all groups are saturated.'''

    # Create inputs, data, and saturation maps
    ngroups = 5
    nrows = 2048
    ncols = 2048
    satvalue = 60000

    data, satmap = setup_nrc_cube(ngroups, nrows, ncols)

    # Add ramp values at or above saturation limit
    data.data[0, 0, 500, 500] = 60000
    data.data[0, 1, 500, 500] = 62000
    data.data[0, 2, 500, 500] = 62000
    data.data[0, 3, 500, 500] = 60000
    data.data[0, 4, 500, 500] = 62000

    # Set saturation value in the saturation model
    satmap.data[500, 500] = satvalue

    # Run the pipeline
    output = do_correction(data, satmap)

    # Make sure all groups are flagged
    assert np.all(output.groupdq[0, :, 500, 500] == dqflags.group['SATURATED'])


def test_subarray_extraction(setup_miri_cube):
    '''Check the step correctly handles subarrays.'''

    # Create input data
    # Create model of data with 0 value array
    ngroups = 50
    nrows = 224
    ncols = 288

    data, satmap = setup_miri_cube(1, 467, ngroups, nrows, ncols)

    # Place DQ flags in DQ array that would be in subarray
    # MASK1550 file has colstart=1, rowstart=467
    satmap.dq[542, 100:105] = 1

    # Test a value of NaN in the reference file
    satmap.data[550, 100] = np.nan

    # Run the pipeline
    output = do_correction(data, satmap)

    # Check for DQ flag in PIXELDQ of subarray image
    assert(output.pixeldq[76, 100] == dqflags.pixel['DO_NOT_USE'])
    assert(output.pixeldq[76, 104] == dqflags.pixel['DO_NOT_USE'])

    # Pixel 84, 100 in subarray maps to 550, 100 in reference file
    # Check that pixel was flagged 'NO_SAT_CHECK'
    assert(output.pixeldq[84, 100] == dqflags.pixel['NO_SAT_CHECK'])


def test_dq_propagation(setup_nrc_cube):
    '''Check PIXELDQ propagation.'''

    # Create inputs, data, and saturation maps
    ngroups = 5
    nrows = 2048
    ncols = 2048
    dqval1 = 5
    dqval2 = 10

    data, satmap = setup_nrc_cube(ngroups, nrows, ncols)

    # Add DQ values to the data and reference file
    data.pixeldq[5, 5] = dqval1
    satmap.dq[5, 5] = dqval2

    # Run the pipeline
    output = do_correction(data, satmap)

    # Make sure DQ values from data and reference file are added in the output
    assert output.pixeldq[5, 5] == dqval1 + dqval2


def test_no_sat_check(setup_nrc_cube):
    '''Check that pixels flagged with NO_SAT_CHECK in the reference file get
       added to the DQ mask and are not flagged as saturated.'''

    # Create inputs, data, and saturation maps
    ngroups = 5
    nrows = 2048
    ncols = 2048
    satvalue = 60000

    data, satmap = setup_nrc_cube(ngroups, nrows, ncols)

    # Add ramp values up to the saturation limit
    data.data[0, 0, 500, 500] = 0
    data.data[0, 1, 500, 500] = 20000
    data.data[0, 2, 500, 500] = 40000
    data.data[0, 3, 500, 500] = 60000
    data.data[0, 4, 500, 500] = 62000   # Signal reaches saturation limit

    # Set saturation value in the saturation model & DQ value for NO_SAT_CHECK
    satmap.data[500, 500] = satvalue
    satmap.dq[500, 500] = dqflags.pixel['NO_SAT_CHECK']

    # Run the pipeline
    output = do_correction(data, satmap)

    # Make sure output GROUPDQ does not get flagged as saturated
    # Make sure PIXELDQ is set to NO_SAT_CHECK
    assert np.all(output.groupdq[0, :, 500, 500] != dqflags.group['SATURATED'])
    assert output.pixeldq[500, 500] == dqflags.pixel['NO_SAT_CHECK']


def test_nans_in_mask(setup_nrc_cube):
    '''Check that pixels in the reference files that have value NaN are not
       flagged as saturated in the data and that in the PIXELDQ array the
       pixel is set to NO_SAT_CHECK.'''

    # Create inputs, data, and saturation maps
    ngroups = 5
    nrows = 2048
    ncols = 2048
    huge_num = 100000.

    data, satmap = setup_nrc_cube(ngroups, nrows, ncols)

    # Add ramp values up to the saturation limit
    data.data[0, 0, 500, 500] = 0
    data.data[0, 1, 500, 500] = 20000
    data.data[0, 2, 500, 500] = 40000
    data.data[0, 3, 500, 500] = 60000
    data.data[0, 4, 500, 500] = 62000

    # Set saturation value for pixel to NaN
    satmap.data[500, 500] = np.nan

    # Run the pipeline
    correct_for_NaN(satmap.data, satmap.dq)
    output = do_correction(data, satmap)

    # Check that NaN reference value gets reset to HUGE_NUM
    # Check that reference DQ is set to NO_SAT_CHECK
    # Check that output GROUPDQ is not flagged as saturated
    # Check that output PIXELDQ is set to NO_SAT_CHECK
    assert satmap.data[500, 500] == huge_num
    assert satmap.dq[500, 500] == dqflags.pixel['NO_SAT_CHECK']
    assert np.all(output.groupdq[0, :, 500, 500] != dqflags.group['SATURATED'])
    assert output.pixeldq[500, 500] == dqflags.pixel['NO_SAT_CHECK']


def test_full_step(setup_nrc_cube):
    '''Test full run of the SaturationStep.'''

    # Create inputs, data, and saturation maps
    ngroups = 5
    nrows = 2048
    ncols = 2048

    data, satmap = setup_nrc_cube(ngroups, nrows, ncols)

    # Add ramp values up to the saturation limit
    data.data[0, 0, 500, 500] = 0
    data.data[0, 1, 500, 500] = 20000
    data.data[0, 2, 500, 500] = 40000
    data.data[0, 3, 500, 500] = 70000   # Signal reaches saturation limit
    data.data[0, 4, 500, 500] = 73000

    # Run the pipeline
    output = SaturationStep.call(data)

    # Check that correct pixel and group 3+ are flagged as saturated
    # Check that other pixel and groups are not flagged
    assert dqflags.group['SATURATED'] == np.max(output.groupdq[0, :, 500, 500])
    assert np.all(output.groupdq[0, 3:, 500, 500] == dqflags.group['SATURATED'])
    assert np.all(output.groupdq[0, :3, 500, 500] != dqflags.group['SATURATED'])
    assert np.all(output.groupdq[0, :, 100, 100] != dqflags.group['SATURATED'])


@pytest.fixture(scope='function')
def setup_nrc_cube():
    ''' Set up fake NIRCam data to test.'''

    def _cube(ngroups, nrows, ncols):

        nints = 1

        data_model = RampModel((nints, ngroups, nrows, ncols))
        data_model.meta.subarray.xstart = 1
        data_model.meta.subarray.ystart = 1
        data_model.meta.subarray.xsize = ncols
        data_model.meta.subarray.ysize = nrows
        data_model.meta.exposure.ngroups = ngroups
        data_model.meta.instrument.name = 'NIRCAM'
        data_model.meta.instrument.detector = 'NRCA1'
        data_model.meta.observation.date = '2017-10-01'
        data_model.meta.observation.time = '00:00:00'

        saturation_model = SaturationModel((2048, 2048))
        saturation_model.meta.subarray.xstart = 1
        saturation_model.meta.subarray.ystart = 1
        saturation_model.meta.subarray.xsize = 2048
        saturation_model.meta.subarray.ysize = 2048
        saturation_model.meta.instrument.name = 'NIRCAM'
        saturation_model.meta.description = 'Fake data.'
        saturation_model.meta.telescope = 'JWST'
        saturation_model.meta.reftype = 'SaturationModel'
        saturation_model.meta.author = 'Alicia'
        saturation_model.meta.pedigree = 'Dummy'
        saturation_model.meta.useafter = '2015-10-01T00:00:00'

        return data_model, saturation_model

    return _cube


@pytest.fixture(scope='function')
def setup_miri_cube():
    ''' Set up fake MIRI data to test.'''

    def _cube(xstart, ystart, ngroups, nrows, ncols):

        nints = 1

        # create a JWST datamodel for MIRI data
        data_model = RampModel((nints, ngroups, nrows, ncols))
        data_model.data += 1
        data_model.meta.instrument.name = 'MIRI'
        data_model.meta.instrument.detector = 'MIRIMAGE'
        data_model.meta.instrument.filter = 'F1500W'
        data_model.meta.instrument.band = 'N/A'
        data_model.meta.observation.date = '2016-06-01'
        data_model.meta.observation.time = '00:00:00'
        data_model.meta.exposure.type = 'MIR_IMAGE'
        data_model.meta.subarray.name = 'MASK1550'
        data_model.meta.subarray.xstart = xstart
        data_model.meta.subarray.xsize = ncols
        data_model.meta.subarray.ystart = ystart
        data_model.meta.subarray.ysize = nrows

        # create a saturation model for the saturation step
        saturation_model = SaturationModel((1032, 1024))
        saturation_model.meta.description = 'Fake data.'
        saturation_model.meta.telescope = 'JWST'
        saturation_model.meta.reftype = 'SaturationModel'
        saturation_model.meta.author = 'Alicia'
        saturation_model.meta.pedigree = 'Dummy'
        saturation_model.meta.useafter = '2015-10-01T00:00:00'
        saturation_model.meta.instrument.name = 'MIRI'
        saturation_model.meta.instrument.detector = 'MIRIMAGE'
        saturation_model.meta.subarray.xstart = 1
        saturation_model.meta.subarray.xsize = 1024
        saturation_model.meta.subarray.ystart = 1
        saturation_model.meta.subarray.ysize = 1032

        return data_model, saturation_model

    return _cube
