""" Work horse routines used for building ifu spectral cubes
"""

import time
import numpy as np
import logging
import math
from ..model_blender import blendmeta
from .. import datamodels
from ..assign_wcs import pointing
from jwst.transforms.models import _toindex
from astropy.stats import circmean
from astropy import units as u
from gwcs import wcstools
from ..assign_wcs import nirspec
from ..datamodels import dqflags
from . import cube_build_wcs_util
from . import cube_overlap
from . import cube_cloud
from . import coord

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class IFUCubeData():

    def __init__(self,
                 pipeline,
                 input_filenames,
                 input_models,
                 output_name_base,
                 output_type,
                 instrument,
                 list_par1,
                 list_par2,
                 instrument_info,
                 master_table,
                 **pars_cube):
        """ Class IFUCube holds the high level data for each IFU Cube
        """
        self.new_code = 0
        self.input_filenames = input_filenames
        self.pipeline = pipeline

        self.input_models = input_models  # needed when building single mode IFU cubes
        self.output_name_base = output_name_base
        self.num_files = None

        self.instrument = instrument
        self.list_par1 = list_par1
        self.list_par2 = list_par2
        self.instrument_info = instrument_info  # dictionary class imported in cube_build.py
        self.master_table = master_table
        self.output_type = output_type

        self.scale1 = pars_cube.get('scale1')
        self.scale2 = pars_cube.get('scale2')
        self.scalew = pars_cube.get('scalew')
        self.rois = pars_cube.get('rois')
        self.roiw = pars_cube.get('roiw')

        self.spatial_size = None
        self.spectral_size = None
        self.interpolation = pars_cube.get('interpolation')
        self.coord_system = pars_cube.get('coord_system')
        self.wavemin = pars_cube.get('wavemin')
        self.wavemax = pars_cube.get('wavemax')
        self.weighting = pars_cube.get('weighting')
        self.weight_power = pars_cube.get('weight_power')
        self.debug = pars_cube.get('debug')
        self.xdebug = pars_cube.get('xdebug')
        self.ydebug = pars_cube.get('ydebug')
        self.zdebug = pars_cube.get('zdebug')
        self.skip_dqflagging = pars_cube.get('skip_dqflagging')
        self.spaxel_debug = pars_cube.get('spaxel_debug')

        self.num_bands = 0
        self.output_name = ''
        self.this_cube_filenames = []

        self.soft_rad = None
        self.scalerad = None
        self.linear_wavelength = True
        self.roiw_table = None
        self.rois_table = None
        self.softrad_table = None
        self.scalerad_table = None
        self.weight_power_table = None
        self.wavelength_table = None

        self.cdelt1 = None
        self.cdelt2 = None
        self.cdelt3 = None
        self.crpix1 = None
        self.crpix2 = None
        self.crpix3 = None
        self.crval1 = None
        self.crval2 = None
        self.crval3 = None
        self.naxis1 = None
        self.naxis2 = None
        self.naxis3 = None
        self.cdelt3_normal = None

        self.a_min = 0
        self.a_max = 0
        self.b_min = 0
        self.b_max = 0
        self.lambda_min = 0
        self.lambda_max = 0
        self.xcoord = None
        self.ycoord = None
        self.zcoord = None

        self.tolerance_dq_overlap = 0.05  # spaxel has to have 5% overlap to flag in FOV
        self.overlap_partial = 4  # intermediate flag
        self.overlap_full = 2    # intermediate flag
        self.overlap_hole = dqflags.pixel['DO_NOT_USE']
        self.overlap_no_coverage = dqflags.pixel['NON_SCIENCE']
# **************************************************************

    def check_ifucube(self):

        """ Perform some quick checks that the type of cube to be produced
        conforms to rules

        Raises
        ------
        IncorrectInput
          Interpolation = area was selected for when input data is more than
          one file or model
        AreaInterpolation
          If Inputerpolate = area then no user selected value can be set for
          beta dimension of the output cube
        """
        num1 = len(self.list_par1)
        num_files = 0
        for i in range(num1):
            this_a = self.list_par1[i]
            this_b = self.list_par2[i]

            n = len(self.master_table.FileMap[self.instrument][this_a][this_b])
            num_files = num_files + n
        self.num_files = num_files
# do some basic checks on the cubes
        if(self.interpolation == "area"):
            if(num_files > 1):
                raise IncorrectInput("For interpolation = area, only one file can" +
                                     " be used to created the cube")
            if(len(self.list_par1) > 1):
                raise IncorrectInput("For interpolation = area, only a single channel" +
                                     " can be used to created the cube. Use --channel=# option")
            if(self.scale2 != 0):
                raise AreaInterpolation("When using interpolation = area, the output" +
                                        " coordinate system is alpha-beta" +
                                        " The beta dimension (naxis2) has a one to one" +
                                        " mapping between slice_no and " +
                                        " beta coordinate.")

        if(self.coord_system == "alpha-beta"):
            if(num_files > 1):
                raise IncorrectInput("Cubes built in alpha-beta coordinate system" +
                                     " are built from a single file")
# ________________________________________________________________________________

    def define_cubename(self):
        """ Define the base output name
        """
        if self.pipeline == 2:
            newname = self.output_name_base + '_s3d.fits'
        else:
            if self.instrument == 'MIRI':
                channels = []
                for ch in self.list_par1:
                    if ch not in channels:
                        channels.append(ch)
                    number_channels = len(channels)
                    ch_name = '_ch'
                    for i in range(number_channels):
                        ch_name = ch_name + channels[i]
                        if i < number_channels - 1:
                            ch_name = ch_name + '-'

                subchannels = list(set(self.list_par2))
                number_subchannels = len(subchannels)
                b_name = ''
                for i in range(number_subchannels):
                    b_name = b_name + subchannels[i]
                    if i > 1:
                        b_name = b_name + '-'
                b_name = b_name.lower()
                newname = self.output_name_base + ch_name + '-' + b_name + \
                    '_s3d.fits'
                if self.coord_system == 'alpha-beta':
                    newname = self.output_name_base + ch_name + '-' + b_name + \
                        '_ab_s3d.fits'
                if self.output_type == 'single':
                    newname = self.output_name_base + ch_name + '-' + b_name + \
                        '_single_s3d.fits'
# ________________________________________________________________________________
            elif self.instrument == 'NIRSPEC':
                fg_name = '_'
                for i in range(len(self.list_par1)):
                    fg_name = fg_name + self.list_par1[i] + '-' + self.list_par2[i]
                    if(i < self.num_bands - 1):
                        fg_name = fg_name + '-'
                fg_name = fg_name.lower()
                newname = self.output_name_base + fg_name + '_s3d.fits'
                if self.output_type == 'single':
                    newname = self.output_name_base + fg_name + '_single_s3d.fits'
# ______________________________________________________________________________
        if self.output_type != 'single':
            log.info('Output Name: %s', newname)
        return newname
# _______________________________________________________________________

    def set_geometry(self, footprint):
        """ Based on the ra,dec and wavelength footprint set up the size
        of the cube in the tangent plane projected coordinate system.

        Parameters
        ----------
        footprint: tuple
          holds min and max or ra,dec, and wavelength for the cube
          footprint
        """

        ra_min, ra_max, dec_min, dec_max, lambda_min, lambda_max = footprint

        dec_ave = (dec_min + dec_max) / 2.0

        # we can not average ra values because of the convergence
        # of hour angles.
        ravalues = np.zeros(2)
        ravalues[0] = ra_min
        ravalues[1] = ra_max

        # astropy circmean assumes angles are in radians,
        # we have angles in degrees
        ra_ave = circmean(ravalues * u.deg).value

        self.crval1 = ra_ave
        self.crval2 = dec_ave
        xi_center, eta_center = coord.radec2std(self.crval1, self.crval2,
                                                ra_ave, dec_ave)
        xi_min, eta_min = coord.radec2std(self.crval1, self.crval2,
                                          ra_min, dec_min)
        xi_max, eta_max = coord.radec2std(self.crval1, self.crval2,
                                          ra_max, dec_max)
# ________________________________________________________________________________
# find the CRPIX1 CRPIX2 - xi and eta centered at 0,0
# to find location of center abs of min values is how many pixels

        n1a = int(math.ceil(math.fabs(xi_min) / self.cdelt1))
        n2a = int(math.ceil(math.fabs(eta_min) / self.cdelt2))

        n1b = int(math.ceil(math.fabs(xi_max) / self.cdelt1))
        n2b = int(math.ceil(math.fabs(eta_max) / self.cdelt2))

        xi_min = 0.0 - (n1a * self.cdelt1) - (self.cdelt1 / 2.0)
        xi_max = (n1b * self.cdelt1) + (self.cdelt1 / 2.0)

        eta_min = 0.0 - (n2a * self.cdelt2) - (self.cdelt2 / 2.0)
        eta_max = (n2b * self.cdelt2) + (self.cdelt2 / 2.0)

        self.crpix1 = float(n1a) + 1.0
        self.crpix2 = float(n2a) + 1.0

        self.naxis1 = n1a + n1b
        self.naxis2 = n2a + n2b

        self.a_min = xi_min
        self.a_max = xi_max
        self.b_min = eta_min
        self.b_max = eta_max
# center of spaxels
        self.xcoord = np.zeros(self.naxis1)
        xstart = xi_min + self.cdelt1 / 2.0
        for i in range(self.naxis1):
            self.xcoord[i] = xstart
            xstart = xstart + self.cdelt1

        self.ycoord = np.zeros(self.naxis2)
        ystart = eta_min + self.cdelt2 / 2.0
        for i in range(self.naxis2):
            self.ycoord[i] = ystart
            ystart = ystart + self.cdelt2

        ygrid = np.zeros(self.naxis2 * self.naxis1)
        xgrid = np.zeros(self.naxis2 * self.naxis1)

        k = 0
        ystart = self.ycoord[0]
        for i in range(self.naxis2):
            xstart = self.xcoord[0]
            for j in range(self.naxis1):
                xgrid[k] = xstart
                ygrid[k] = ystart
                xstart = xstart + self.cdelt1
                k = k + 1
            ystart = ystart + self.cdelt2

#        ycube,xcube = np.mgrid[0:self.naxis2,
#                               0:self.naxis1]
#        xcube = xcube.flatten()
#        ycube = ycube.flatten()

        self.xcenters = xgrid
        self.ycenters = ygrid
# _______________________________________________________________________
        # set up the lambda (z) coordinate of the cube
        self.cdelt3_normal = None
        if self.linear_wavelength:
            self.lambda_min = lambda_min
            self.lambda_max = lambda_max
            range_lambda = self.lambda_max - self.lambda_min
            self.naxis3 = int(math.ceil(range_lambda / self.cdelt3))

            # adjust max based on integer value of naxis3
            lambda_center = (self.lambda_max + self.lambda_min) / 2.0
            self.lambda_min = lambda_center - (self.naxis3 / 2.0) * self.cdelt3
            self.lambda_max = self.lambda_min + (self.naxis3) * self.cdelt3

            self.zcoord = np.zeros(self.naxis3)
            # CRPIX3 for FITS is 1 (center of first pixel)
            # CRVAL3 then is lambda_min + self.cdelt3/ 2.0, which is also zcoord[0]
            self.crval3 = self.lambda_min + self.cdelt3 / 2.0
            self.crpix3 = 1.0
            zstart = self.lambda_min + self.cdelt3 / 2.0
            for i in range(self.naxis3):
                self.zcoord[i] = zstart
                zstart = zstart + self.cdelt3
        else:
            self.naxis3 = len(self.wavelength_table)
            self.zcoord = np.asarray(self.wavelength_table)
            self.crval3 = self.wavelength_table[0]
            self.crpix3 = 1.0
        # set up the cdelt3_normal normalizing array used in cube_cloud.py
        cdelt3_normal = np.zeros(self.naxis3)
        for j in range(self.naxis3 - 1):
            cdelt3_normal[j] = self.zcoord[j + 1] - self.zcoord[j]

        cdelt3_normal[self.naxis3 - 1] = cdelt3_normal[self.naxis3 - 2]
        self.cdelt3_normal = cdelt3_normal
# _______________________________________________________________________

    def set_geometryAB(self, footprint):
        """Based on the alpha, beta and wavelength footprint set up the
        size of the cube in alpha-beta space.

        This will be a single exposure cube - small FOV assume
        rectangular coord system.

        Parameters
        ----------
        footprint : tuple
           Holds the min and max alpha, beta and wavelength values of
           cube on sky
        """
        self.a_min, self.a_max, self.b_min, self.b_max, self.lambda_min, self.lambda_max = footprint

        # set up the a (x) coordinates of the cube
        range_a = self.a_max - self.a_min
        self.naxis1 = int(math.ceil(range_a / self.cdelt1))

        # adjust min and max based on integer value of naxis1
        a_center = (self.a_max + self.a_min) / 2.0
        self.a_min = a_center - (self.naxis1 / 2.0) * self.cdelt1
        self.a_max = a_center + (self.naxis1 / 2.0) * self.cdelt1

        self.xcoord = np.zeros(self.naxis1)
        self.crval1 = self.a_min
        self.crpix1 = 0.5
        xstart = self.a_min + self.cdelt1 / 2.0
        for i in range(self.naxis1):
            self.xcoord[i] = xstart
            xstart = xstart + self.cdelt1
# _______________________________________________________________________
        # set up the lambda (z) coordinate of the cube
        range_lambda = self.lambda_max - self.lambda_min
        self.naxis3 = int(math.ceil(range_lambda / self.cdelt3))

        # adjust max based on integer value of naxis3
        lambda_center = (self.lambda_max + self.lambda_min) / 2.0

        self.lambda_min = lambda_center - (self.naxis3 / 2.0) * self.cdelt3
        self.lambda_max = lambda_center + (self.naxis3 / 2.0) * self.cdelt3

        self.lambda_max = self.lambda_min + (self.naxis3) * self.cdelt3

        self.zcoord = np.zeros(self.naxis3)
        zstart = self.lambda_min + self.cdelt3 / 2.0
#        self.crval3 = self.lambda_min
        self.crval3 = zstart
        self.crpix3 = 1.0
        for i in range(self.naxis3):
            self.zcoord[i] = zstart
            zstart = zstart + self.cdelt3
# _______________________________________________________________________
        # set up the naxis2 parameters
        range_b = self.b_max - self.b_min

        self.naxis2 = int(math.ceil(range_b / self.cdelt2))
        b_center = (self.b_max + self.b_min) / 2.0
        # adjust min and max based on integer value of naxis2
        self.b_max = b_center + (self.naxis2 / 2.0) * self.cdelt2
        self.b_min = b_center - (self.naxis2 / 2.0) * self.cdelt2

        self.ycoord = np.zeros(self.naxis2)
        self.crval2 = self.b_min
        self.crpix2 = 0.5
        ystart = self.b_min + self.cdelt2 / 2.0
        for i in range(self.naxis2):
            self.ycoord[i] = ystart
            ystart = ystart + self.cdelt2
# _______________________________________________________________________

    def print_cube_geometry(self):

        """Print out the general properties of the size of the IFU Cube
        """

        log.info('Cube Geometry:')
        if self.coord_system == 'alpha-beta':
            log.info('axis#  Naxis  CRPIX    CRVAL      CDELT(arcsec)  Min & Max (alpha, beta arcsec)')
        else:
            log.info('axis#  Naxis  CRPIX    CRVAL      CDELT(arcsec)  Min & Max (xi, eta arcsec)')
            log.info('Axis 1 %5d  %5.2f %12.8f %12.8f %12.8f %12.8f',
                     self.naxis1, self.crpix1, self.crval1, self.cdelt1,
                     self.a_min, self.a_max)
            log.info('Axis 2 %5d  %5.2f %12.8f %12.8f %12.8f %12.8f',
                     self.naxis2, self.crpix2, self.crval2, self.cdelt2,
                     self.b_min, self.b_max)
            if self.linear_wavelength:
                log.info('axis#  Naxis  CRPIX    CRVAL      CDELT(microns)  Min & Max (microns)')
                log.info('Axis 3 %5d  %5.2f %12.8f %12.8f %12.8f %12.8f',
                         self.naxis3, self.crpix3, self.crval3, self.cdelt3,
                         self.lambda_min, self.lambda_max)

            if not self.linear_wavelength:
                log.info('Non-linear wavelength dimension; CDELT3 variable')
                log.info('axis#  Naxis  CRPIX    CRVAL     Min & Max (microns)')
                log.info('Axis 3 %5d  %5.2f %12.8f %12.8f %12.8f',
                         self.naxis3, self.crpix3, self.crval3,
                         self.wavelength_table[0], self.wavelength_table[self.naxis3 - 1])

        if self.instrument == 'MIRI':
            # length of channel and subchannel are the same
            number_bands = len(self.list_par1)
            for i in range(number_bands):
                this_channel = self.list_par1[i]
                this_subchannel = self.list_par2[i]
                log.info('Cube covers channel, subchannel: %s, %s ', this_channel, this_subchannel)
        elif self.instrument == 'NIRSPEC':
            # number of filters and gratings are the same
            number_bands = len(self.list_par1)
            for i in range(number_bands):
                this_fwa = self.list_par2[i]
                this_gwa = self.list_par1[i]
                log.info('Cube covers grating, filter: %s, %s ', this_gwa, this_fwa)
# ________________________________________________________________________________

    def build_ifucube(self):

        """ Create the IFU cube

        1. Loop over every band contained in the IFU cube and read in the data
        associated with the band
        2. map_detector_to_output_frame: Maps the detector data to the cube output coordinate system
        3. For each mapped detector pixel the ifu cube spaxel located in the region of
        interest. There are three different routines to do this step each of them use
        a slighly different weighting function in how to combine the detector fluxs that
        fall within a region of influence from the spaxel center
        a. cube_cloud:match_det2_cube_msm: This routine uses the modified
        shepard method to determing the weighting function, which weights the detector
        fluxes based on the distance between the detector center and spaxel center.
        b. cube_cloud:match_det2_cube_miripsf the weighting function based  width of the
        psf and lsf.
        c. cube_overlap.match_det2cube is only for single exposure, single band cubes and
        the ifucube in created in the detector plane. The weighting function is based on
        the overlap of between the detector pixel and spaxel. This method is simplified
        to determine the overlap in the alpha-wavelength plane.
        4. find_spaxel_flux: find the final flux assoicated with each spaxel
        5. setup_final_ifucube_model
        6. output_ifucube

        Returns
        -------
        Returns an ifu cube

        """

        self.output_name = self.define_cubename()
        total_num = self.naxis1 * self.naxis2 * self.naxis3
        self.spaxel_flux = np.zeros(total_num)
        self.spaxel_weight = np.zeros(total_num)
        self.spaxel_iflux = np.zeros(total_num)
        self.spaxel_dq = np.zeros((self.naxis3, self.naxis2 * self.naxis1), dtype=np.uint32)

        spaxel_ra = None
        spaxel_dec = None
        spaxel_wave = None
# ______________________________________________________________________________
# Only preformed if weighting = MIRIPSF, first convert xi,eta cube to
# v2,v3,wave. This information if past to cube_cloud and for each
# input_model the v2,v3, wave is converted to alpha,beta in detector plane
# ra,dec, wave is independent of input_model
# v2,v3, alpha,beta depends on the input_model
        if self.weighting == 'miripsf':
            spaxel_ra = np.zeros(total_num)
            spaxel_dec = np.zeros(total_num)
            spaxel_wave = np.zeros(total_num)

            nxy = self.xcenters.size
            nz = self.zcoord.size
            for iz in range(nz):
                istart = iz * nxy
                for ixy in range(nxy):
                    ii = istart + ixy
                    spaxel_ra[ii], spaxel_dec[ii] = coord.std2radec(self.crval1,
                                                                    self.crval2,
                                                                    self.xcenters[ixy],
                                                                    self.ycenters[ixy])
                    spaxel_wave[ii] = self.zcoord[iz]
# ______________________________________________________________________________
        subtract_background = True

        # now need to loop over every file that covers this
        # channel/subchannel (MIRI)
        # or Grating/filter(NIRSPEC)
        # and map the detector pixels to the cube spaxel

        number_bands = len(self.list_par1)

        for i in range(number_bands):
            this_par1 = self.list_par1[i]
            this_par2 = self.list_par2[i]
            nfiles = len(self.master_table.FileMap[self.instrument][this_par1][this_par2])
# ________________________________________________________________________________
# loop over the files that cover the spectral range the cube is for
            for k in range(nfiles):
                ifile = self.master_table.FileMap[self.instrument][this_par1][this_par2][k]
                self.this_cube_filenames.append(ifile)
                log.debug("Working on Band defined by: %s %s ", this_par1, this_par2)
# --------------------------------------------------------------------------------
                if self.interpolation == 'pointcloud':
                    t0 = time.time()
                    pixelresult = self.map_detector_to_outputframe(this_par1,
                                                                   subtract_background,
                                                                   ifile)

                    coord1, coord2, wave, flux, slice_no, rois_pixel, roiw_pixel, weight_pixel,\
                        softrad_pixel, scalerad_pixel, alpha_det, beta_det = pixelresult
                    t1 = time.time()
                    log.info("Time to transform pixels to output frame = %.1f s" % (t1 - t0,))

                    # If setting the DQ plane of the IFU
                    if self.skip_dqflagging:
                        log.info("Skipping setting DQ flagging")
                    else:
                        t0 = time.time()
                        roiw_ave = np.mean(roiw_pixel)
                        self.map_fov_to_dqplane(this_par1, coord1, coord2, wave, roiw_ave, slice_no)
                        t1 = time.time()
                        log.info("Time to set initial dq values = %.1f s" % (t1 - t0,))
                    if self.weighting == 'msm' or self.weighting == 'emsm':
                        t0 = time.time()
                        cube_cloud.match_det2cube_msm(self.naxis1, self.naxis2, self.naxis3,
                                                      self.cdelt1, self.cdelt2,
                                                      self.cdelt3_normal,
                                                      self.xcenters, self.ycenters, self.zcoord,
                                                      self.spaxel_flux,
                                                      self.spaxel_weight,
                                                      self.spaxel_iflux,
                                                      flux,
                                                      coord1, coord2, wave,
                                                      self.weighting,
                                                      rois_pixel, roiw_pixel,
                                                      weight_pixel,
                                                      softrad_pixel,
                                                      scalerad_pixel)

                        t1 = time.time()
                        log.info("Time to match file to ifucube = %.1f s" % (t1 - t0,))
# ________________________________________________________________________________
                    elif self.weighting == 'miripsf':
                        with datamodels.IFUImageModel(ifile) as input_model:
                            wave_resol = self.instrument_info.Get_RP_ave_Wave(this_par1,
                                                                              this_par2)

                            alpha_resol = self.instrument_info.Get_psf_alpha_parameters()
                            beta_resol = self.instrument_info.Get_psf_beta_parameters()

                            worldtov23 = input_model.meta.wcs.get_transform("world", "v2v3")
                            v2ab_transform = input_model.meta.wcs.get_transform('v2v3',
                                                                                'alpha_beta')

                            spaxel_v2, spaxel_v3, zl = worldtov23(spaxel_ra,
                                                                  spaxel_dec,
                                                                  spaxel_wave)

                            spaxel_alpha, spaxel_beta, spaxel_wave = v2ab_transform(spaxel_v2,
                                                                                    spaxel_v3,
                                                                                    zl)
                            cube_cloud.match_det2cube_miripsf(alpha_resol,
                                                              beta_resol,
                                                              wave_resol,
                                                              self.naxis1, self.naxis2, self.naxis3,
                                                              self.xcenters, self.ycenters, self.zcoord,
                                                              self.spaxel_flux,
                                                              self.spaxel_weight,
                                                              self.spaxel_iflux,
                                                              spaxel_alpha, spaxel_beta, spaxel_wave,
                                                              flux,
                                                              coord1, coord2, wave,
                                                              alpha_det, beta_det,
                                                              self.weighting,
                                                              rois_pixel, roiw_pixel,
                                                              weight_pixel,
                                                              softrad_pixel,
                                                              scalerad_pixel)
# --------------------------------------------------------------------------------
# 2D area method - only works for single files and coord_system = 'alpha-beta'
# --------------------------------------------------------------------------------
                elif self.interpolation == 'area':
                    with datamodels.IFUImageModel(ifile) as input_model:
                        det2ab_transform = input_model.meta.wcs.get_transform('detector',
                                                                              'alpha_beta')
                        start_region = self.instrument_info.GetStartSlice(this_par1)
                        end_region = self.instrument_info.GetEndSlice(this_par1)
                        regions = list(range(start_region, end_region + 1))
                        t0 = time.time()
                        for i in regions:
                            log.info('Working on Slice # %d', i)
                            y, x = (det2ab_transform.label_mapper.mapper == i).nonzero()

# getting pixel corner - ytop = y + 1 (routine fails for y = 1024)
                            index = np.where(y < 1023)
                            y = y[index]
                            x = x[index]
                            cube_overlap.match_det2cube(x, y, i,
                                                        start_region,
                                                        input_model,
                                                        det2ab_transform,
                                                        self.spaxel_flux,
                                                        self.spaxel_weight,
                                                        self.spaxel_iflux,
                                                        self.xcoord, self.zcoord,
                                                        self.crval1, self.crval3,
                                                        self.cdelt1, self.cdelt3,
                                                        self.naxis1, self.naxis2)
                        t1 = time.time()

                        log.info("Time to Map All slices on Detector to Cube = %.1f s" % (t1 - t0,))
# _______________________________________________________________________
# Mapped all data to cube or Point Cloud
# now determine Cube Spaxel flux

        t0 = time.time()
        self.find_spaxel_flux()

        self.set_final_dq_flags()
        t1 = time.time()
        log.info("Time to find Cube Flux = %.1f s" % (t1 - t0,))

        ifucube_model = self.setup_final_ifucube_model(0)
# _______________________________________________________________________
# shove Flux and iflux in the  final IFU cube
        self.update_ifucube(ifucube_model)
        return ifucube_model
# ********************************************************************************

    def build_ifucube_single(self):

        """ Build a set of single mode IFU cubes used for outlier detection
        and background matching


        Loop over every band contained in the IFU cube and read in the data
        associated with the band. Map each band to the output cube  coordinate
        system

        """

        # loop over input models
        single_ifucube_container = datamodels.ModelContainer()
        n = len(self.input_models)
        log.info("Number of Single IFU cubes to create = %i" % n)
        this_par1 = self.list_par1[0]  # only one channel is used in this approach
#        this_par2 = None  # not important for this type of mapping

        for j in range(n):
            log.info("Working on next Single IFU Cube = %i" % (j + 1))
            t0 = time.time()
# for each new data model create a new spaxel
            total_num = self.naxis1 * self.naxis2 * self.naxis3
            self.spaxel_flux = np.zeros(total_num)
            self.spaxel_weight = np.zeros(total_num)
            self.spaxel_iflux = np.zeros(total_num)
            self.spaxel_dq = np.zeros((self.naxis3, self.naxis2 * self.naxis1), dtype=np.uint32)

            subtract_background = False

            pixelresult = self.map_detector_to_outputframe(this_par1,
                                                           subtract_background,
                                                           self.input_models[j])

            coord1, coord2, wave, flux, slice_no, rois_pixel, roiw_pixel, weight_pixel, \
                softrad_pixel, scalerad_pixel, alpha_det, beta_det = pixelresult

            cube_cloud.match_det2cube_msm(self.naxis1,
                                          self.naxis2,
                                          self.naxis3,
                                          self.cdelt1, self.cdelt2,
                                          self.cdelt3_normal,
                                          self.xcenters,
                                          self.ycenters,
                                          self.zcoord,
                                          self.spaxel_flux,
                                          self.spaxel_weight,
                                          self.spaxel_iflux,
                                          flux,
                                          coord1, coord2, wave,
                                          self.weighting,
                                          rois_pixel, roiw_pixel,
                                          weight_pixel,
                                          softrad_pixel,
                                          scalerad_pixel)
# _______________________________________________________________________
# shove Flux and iflux in the  final ifucube
            self.find_spaxel_flux()
# now determine Cube Spaxel flux

            ifucube_model = self.setup_final_ifucube_model(j)
            self.update_ifucube(ifucube_model)
            t1 = time.time()
            log.info("Time to Create Single ifucube = %.1f s" % (t1 - t0,))
# _______________________________________________________________________
            single_ifucube_container.append(ifucube_model)

        return single_ifucube_container
# **************************************************************************

    def determine_cube_parameters(self):
        """Determine the spatial and wavelength roi size to use for
        selecting point cloud elements around the spaxel centeres.

        If the IFU cube covers more than 1 band - then use the rules to
        define the Spatial and Wavelength roi size to use for the cube
        Current Rule: using the minimum

        Returns
        -------
        roi size for spatial and wavelength

        """
        # initialize
        wave_roi = None
        weight_power = None

        number_bands = len(self.list_par1)
        spaxelsize = np.zeros(number_bands)
        spectralsize = np.zeros(number_bands)
        rois = np.zeros(number_bands)
        roiw = np.zeros(number_bands)
        power = np.zeros(number_bands)
        softrad = np.zeros(number_bands)
        scalerad = np.zeros(number_bands)
        minwave = np.zeros(number_bands)
        maxwave = np.zeros(number_bands)

        for i in range(number_bands):
            if self.instrument == 'MIRI':
                par1 = self.list_par1[i]
                par2 = self.list_par2[i]
            elif self.instrument == 'NIRSPEC':
                par1 = self.list_par1[i]
                par2 = self.list_par2[i]

            # pull out the values from the cube pars reference file
            roiw[i] = self.instrument_info.GetWaveRoi(par1, par2)
            rois[i] = self.instrument_info.GetSpatialRoi(par1, par2)

            a_scale, b_scale, w_scale = self.instrument_info.GetScale(par1,
                                                                      par2)
            spaxelsize[i] = a_scale
            spectralsize[i] = w_scale

            minwave[i] = self.instrument_info.GetWaveMin(par1, par2)
            maxwave[i] = self.instrument_info.GetWaveMax(par1, par2)
            # values will be set to NONE if cube pars table does not contain them

            power[i] = self.instrument_info.GetMSMPower(par1, par2)
            softrad[i] = self.instrument_info.GetSoftRad(par1, par2)
            scalerad[i] = self.instrument_info.GetScaleRad(par1, par2)
        # Check the spatial size. If it is the same for the array set up the parameters
        all_same = np.all(spaxelsize == spaxelsize[0])

        if all_same:
            self.spatial_size = spaxelsize[0]
            spatial_roi = rois[0]
        # if it is not the same then use the minimum value
        else:
            index_min = np.argmin(spaxelsize)
            self.spatial_size = spaxelsize[index_min]
            spatial_roi = rois[index_min]
        # find min and max wavelength
        min_wave = np.amin(minwave)
        max_wave = np.amax(maxwave)

        if self.wavemin is None:
            self.wavemin = min_wave
        else:
            self.wavemin = np.float64(self.wavemin)

        if self.wavemax is None:
            self.wavemax = max_wave
        else:
            self.wavemax = np.float64(self.wavemax)

        # now check spectral step - this will determine
        # if the wavelength dimension is linear or not
        all_same_spectral = np.all(spectralsize == spectralsize[0])

        # check if scalew has been set - if yes then linear scale
        if self.scalew != 0:
            self.spectral_size = self.scalew
            self.linear_wavelength = True
            wave_roi = np.amin(roiw)
            weight_power = np.amin(power)
            self.soft_rad = np.amin(softrad)
            self.scalerad = np.amin(scalerad)

        # if all bands have the same spectral size then linear_wavelength
        elif all_same_spectral:
            self.spectral_size = spectralsize[0]
            wave_roi = roiw[0]
            weight_power = power[0]
            self.linear_wavelength = True  # added this 10/01/19
            self.soft_rad = softrad[0]
            self.scalerad = scalerad[0]
        else:
            self.linear_wavelength = False
            if self.instrument == 'MIRI':

                table = self.instrument_info.Get_multichannel_table(self.weighting)
                (table_wavelength, table_sroi,
                 table_wroi, table_power,
                 table_softrad, table_scalerad) = table

            # getting NIRSPEC Table Values
            elif self.instrument == 'NIRSPEC':
                # determine if have Prism, Medium or High resolution
                med = ['g140m', 'g235m', 'g395m']
                high = ['g140h', 'g235h', 'g395h']
                prism = ['prism']

                for i in range(number_bands):
                    par1 = self.list_par1[i]
                    if par1 in prism:
                        table = self.instrument_info.Get_prism_table()
                    if par1 in med:
                        table = self.instrument_info.Get_med_table()
                    if par1 in high:
                        table = self.instrument_info.Get_high_table()
                    (table_wavelength, table_sroi,
                     table_wroi, table_power,
                     table_softrad, table_scalerad) = table
            # based on Min and Max wavelength - pull out the tables values that fall in this range
            # find the closest table entries to the self.wavemin and self.wavemax limits
            imin = (np.abs(table_wavelength - self.wavemin)).argmin()
            imax = (np.abs(table_wavelength - self.wavemax)).argmin()

            if imin > 1 and table_wavelength[imin] > self.wavemin:
                imin = imin - 1
            if (imax < len(table_wavelength) and
                self.wavemax > table_wavelength[imax]):
                imax = imax + 1

            # print('wavelengths', self.wavemin, self.wavemax)
            self.roiw_table = table_wroi[imin:imax+1]
            self.rois_table = table_sroi[imin:imax+1]
            if self.num_files < 4:
                self.rois_table = [i*1.5 for i in self.rois_table]

            self.softrad_table = table_softrad[imin:imax+1]
            self.weight_power_table = table_power[imin:imax+1]
            self.scalerad_table = table_scalerad[imin:imax+1]
            self.wavelength_table = table_wavelength[imin:imax+1]

        # check if using default values from the table  (not user set)
        if self.rois == 0.0:
            self.rois = spatial_roi
            # not set by use but determined from tables
            # default rois in tables is designed with a 4 dither pattern
            # increase rois if less than 4 file

            if self.output_type == 'single' or self.num_files < 4:
                self.rois = self.rois * 1.5
                log.info('Increasing spatial region of interest ' +
                         'default value set for 4 dithers %f', self.rois)

        if self.scale1 != 0:
            self.spatial_size = self.scale1

        # set wave_roi and  weight_power to same values if they are in  list
        if self.roiw == 0:
            self.roiw = wave_roi

        if self.weight_power == 0:
            self.weight_power = weight_power

        # catch where self.weight_power, softrad or scalerad could be nan and
        # set to None - this should not happen - these varibles
        if self.weight_power is not None:
            if np.isnan(self.weight_power):
                self.weight_power = None
        if self.soft_rad is not None:
            if np.isnan(self.soft_rad):
                self.soft_rad = None
        if self.scalerad is not None:
            if np.isnan(self.scalerad):
                self.scalerad = None
#        print('spatial size', self.spatial_size)
#        print('spectral size', self.spectral_size)
#        print('spatial roi', self.rois)
#        print('wave min and max', self.wavemin, self.wavemax)
#        print('linear wavelength', self.linear_wavelength)
#        print('roiw', self.roiw)
#        print('output_type',self.output_type)
#        print('weight_power',self.weight_power)
#        print('softrad',self.soft_rad)
#        print('scalerad',self.scalerad)
# ******************************************************************************

    def setup_ifucube_wcs(self):

        """Function to determine the min and max coordinates of the spectral
        cube

        Loop over every datamodel contained in the cube and find the WCS
        of the output cube that contains all the data.

        Returns
        -------
        Footprint of cube: min and max of coordinates of cube.

        Notes
        -----
        If the coordinate system is alpha-beta (MIRI) then min and max
        coordinates of alpha (arc sec), beta (arc sec) and lambda (microns)
        If the coordinate system is world then the min and max of
        ra(degress), dec (degrees) and lambda (microns) is returned.

        """
# _____________________________________________________________________________
        self.cdelt1 = self.spatial_size
        self.cdelt2 = self.spatial_size
        if self.linear_wavelength:
            self.cdelt3 = self.spectral_size

        parameter1 = self.list_par1
        parameter2 = self.list_par2

        a_min = []
        a_max = []
        b_min = []
        b_max = []
        lambda_min = []
        lambda_max = []

        self.num_bands = len(self.list_par1)
        log.info('Number of bands in cube: %i', self.num_bands)

        for i in range(self.num_bands):
            this_a = parameter1[i]
            this_b = parameter2[i]
            log.debug('Working on data from %s, %s', this_a, this_b)
            n = len(self.master_table.FileMap[self.instrument][this_a][this_b])
            log.debug('number of files %d', n)
            for k in range(n):
                amin = 0.0
                amax = 0.0
                bmin = 0.0
                bmax = 0.0
                lmin = 0.0
                lmax = 0.0

                ifile = self.master_table.FileMap[self.instrument][this_a][this_b][k]
# ______________________________________________________________________________
# Open the input data model
# Find the footprint of the image
                with datamodels.IFUImageModel(ifile) as input_model:
                    if self.instrument == 'NIRSPEC':
                        # t0 = time.time()
                        ch_footprint = cube_build_wcs_util.find_footprint_NIRSPEC(
                            input_model,
                            self.coord_system)
                        # t1 = time.time()
                        # print('time to find footprint',t1-t0)

                        amin, amax, bmin, bmax, lmin, lmax = ch_footprint
                        # We might be able to call cmpute_footprint from assign_wcs instead
# ________________________________________________________________________________
                    if self.instrument == 'MIRI':
                        ch_footprint = cube_build_wcs_util.find_footprint_MIRI(
                            input_model,
                            this_a,
                            self.instrument_info,
                            self.coord_system)
                        amin, amax, bmin, bmax, lmin, lmax = ch_footprint
                        # if we call compute_footprint from assign_wcs - need footprint
                        # for band not both channels
                    a_min.append(amin)
                    a_max.append(amax)
                    b_min.append(bmin)
                    b_max.append(bmax)
                    lambda_min.append(lmin)
                    lambda_max.append(lmax)
# ________________________________________________________________________________
    # done looping over files determine final size of cube

        final_a_min = min(a_min)
        final_a_max = max(a_max)
        final_b_min = min(b_min)
        final_b_max = max(b_max)
        # final_lambda_min = min(lambda_min)
        # final_lambda_max = max(lambda_max)

        # wavelength range read in from cube pars reference file
        final_lambda_min = self.wavemin
        final_lambda_max = self.wavemax
        # ______________________________________________________________________
        if self.instrument == 'MIRI' and self.coord_system == 'alpha-beta':
            #  we have a 1 to 1 mapping in beta dimension.
            nslice = self.instrument_info.GetNSlice(parameter1[0])
            log.info('Beta Scale %f ', self.cdelt2)
            self.cdelt2 = (final_b_max - final_b_min) / nslice
            final_b_max = final_b_min + (nslice) * self.cdelt2
            log.info('Changed the Beta Scale dimension so we have 1-1 mapping between beta and slice #')
            log.info('New Beta Scale %f ', self.cdelt2)
# ________________________________________________________________________________
# Test that we have data (NIRSPEC NRS2 only has IFU data for 3 configurations)
        test_a = final_a_max - final_a_min
        test_b = final_b_max - final_b_min
        tolerance1 = 0.00001
        if(test_a < tolerance1 or test_b < tolerance1):
            log.info('No Valid IFU slice data found %f %f ', test_a, test_b)
# ________________________________________________________________________________
        cube_footprint = (final_a_min, final_a_max, final_b_min, final_b_max,
                          final_lambda_min, final_lambda_max)

# ________________________________________________________________________________
    # Based on Scaling and Min and Max values determine naxis1, naxis2, naxis3
    # set cube CRVALs, CRPIXs

        if self.coord_system == 'world':
            self.set_geometry(cube_footprint)
        else:
            self.set_geometryAB(cube_footprint)
        self.print_cube_geometry()
# **************************************************************************

    def map_detector_to_outputframe(self, this_par1,
                                    subtract_background,
                                    ifile):
        from ..mrs_imatch.mrs_imatch_step import apply_background_2d
# **************************************************************************
        """Loop over a file and map the detector pixels to the output cube

        Return the coordinates of all the detector pixel in the output frame.
        In addition, an array of pixel fluxes and weighing parameters are
        detemined. The pixel flux and weighing parameters are use later in
        the processto find the final flux of a cube spaxel based on the pixel
        fluxes and pixel weighing parameters that fall within the roi of
        spaxel center

        Parameter
        ----------
        this_par1 : str
           for MIRI this is the channel # for NIRSPEC this is the grating name
           only need for MIRI to distinguish which channel on the detector we have
        subtract_background : boolean
           if TRUE then subtract the background found in the mrs_imatch step
        ifile : datamodel
           input data model

        Returns
        -------
        coord1 : numpy.ndarray
           coordinate for axis1 in output cube for mapped pixel
        coord2: numpy.ndarray
           coordinate for axis2 in output cube for mapped pixel
        wave: numpy.ndarray
           wavelength associated with coord1,coord2
        flux: numpy.ndarray
           flux associated with coord1, coord2
        rois_det: float
           spatial roi size to use
        roiw_det: numpy.ndarray
           spectral roi size associated with coord1,coord2
        weight_det : numpy.ndarray
            weighting parameter assocation with coord1,coord2
        softrad_det : numpy.ndarray
            weighting parameter assocation with coord1,coord2
        alpha_det : numpy.ndarray
           alpha coordinate of pixels
        beta_det : numpy.ndarray
           beta coordinate of pixel
        """
# intitalize alpha_det and beta_det to None. These are filled in
# if the instrument is MIRI and the weighting is miripsf

        alpha_det = None
        beta_det = None
        coord1 = None
        coord2 = None
        flux = None
        wave = None
        slice_no = None  # Slice number
# Open the input data model
        with datamodels.IFUImageModel(ifile) as input_model:
            # check if background sky matching as been done
            # mrs_imatch step. THis is only for MRS data at this time
            # but go head and check it before splitting by instrument
            # the polynomial should be empty for NIRSPEC

            num_ch_bgk = len(input_model.meta.background.polynomial_info)
            if(num_ch_bgk > 0 and subtract_background):
                for ich_num in range(num_ch_bgk):
                    poly = input_model.meta.background.polynomial_info[ich_num]
                    poly_ch = poly.channel
                    if(poly_ch == this_par1):
                        apply_background_2d(input_model, poly_ch, subtract=True)
# --------------------------------------------------------------------------------
            if self.instrument == 'MIRI':

                # find the slice number of each pixel and fill in slice_det
                ysize, xsize = input_model.data.shape
                slice_det = np.zeros((ysize, xsize), dtype=int)
                det2ab_transform = input_model.meta.wcs.get_transform('detector',
                                                                      'alpha_beta')
                start_region = self.instrument_info.GetStartSlice(this_par1)
                end_region = self.instrument_info.GetEndSlice(this_par1)
                regions = list(range(start_region, end_region + 1))
                for i in regions:
                    ys, xs = (det2ab_transform.label_mapper.mapper == i).nonzero()
                    xind = _toindex(xs)
                    yind = _toindex(ys)
                    xind = np.ndarray.flatten(xind)
                    yind = np.ndarray.flatten(yind)
                    slice_det[yind, xind] = i

                # define the x,y detector values of channel to be mapped to desired coordinate system
                xstart, xend = self.instrument_info.GetMIRISliceEndPts(this_par1)
                y, x = np.mgrid[:ysize, xstart:xend]
                y = np.reshape(y, y.size)
                x = np.reshape(x, x.size)

                if self.coord_system == 'world':
                    ra, dec, wave = input_model.meta.wcs(x, y)
                    valid1 = ~np.isnan(ra)
                    ra = ra[valid1]
                    dec = dec[valid1]
                    wave = wave[valid1]
                    x = x[valid1]
                    y = y[valid1]

                    xind = _toindex(x)
                    yind = _toindex(y)
                    xind = np.ndarray.flatten(xind)
                    yind = np.ndarray.flatten(yind)
                    slice_no = slice_det[yind, xind]

                    if self.weighting == 'miripsf':
                        alpha, beta, lam = det2ab_transform(x, y)
                elif self.coord_system == 'alpha-beta':
                    alpha, beta, wave = det2ab_transform(x, y)
                    valid1 = ~np.isnan(coord1)
                    alpha = alpha[valid1]
                    beta = beta[valid1]
                    wave = wave[valid1]
                    x = x[valid1]
                    y = y[valid1]
# ________________________________________________________________________________
            elif self.instrument == 'NIRSPEC':
                # initialize the ra,dec, and wavelength arrays
                # we will loop over slice_nos and fill in values
                # the flag_det will be set when a slice_no pixel is filled in
                #   at the end we will use this flag to pull out valid data

                ysize, xsize = input_model.data.shape
                ra_det = np.zeros((ysize, xsize))
                dec_det = np.zeros((ysize, xsize))
                lam_det = np.zeros((ysize, xsize))
                flag_det = np.zeros((ysize, xsize))
                slice_det = np.zeros((ysize, xsize), dtype=int)
                # for NIRSPEC each file has 30 slices
                # wcs information access seperately for each slice
                nslices = 30
                log.info("Mapping each NIRSpec slice to sky; this takes a while for NIRSpec data")
                for ii in range(nslices):
                    slice_wcs = nirspec.nrs_wcs_set_input(input_model, ii)
                    x, y = wcstools.grid_from_bounding_box(slice_wcs.bounding_box)
                    ra, dec, lam = slice_wcs(x, y)

                    # the slices are curved on detector so a rectangular region
                    # returns NaNs
                    valid = ~np.isnan(lam)
                    ra = ra[valid]
                    dec = dec[valid]
                    lam = lam[valid]
                    x = x[valid]
                    y = y[valid]

                    xind = _toindex(x)
                    yind = _toindex(y)
                    xind = np.ndarray.flatten(xind)
                    yind = np.ndarray.flatten(yind)
                    ra = np.ndarray.flatten(ra)
                    dec = np.ndarray.flatten(dec)
                    lam = np.ndarray.flatten(lam)
                    ra_det[yind, xind] = ra
                    dec_det[yind, xind] = dec
                    lam_det[yind, xind] = lam
                    flag_det[yind, xind] = 1
                    slice_det[yind, xind] = ii+1

                # after looping over slices  - pull out valid values
                valid_data = np.where(flag_det == 1)
                y, x = valid_data
                ra = ra_det[valid_data]
                dec = dec_det[valid_data]
                wave = lam_det[valid_data]
                slice_no = slice_det[valid_data]
# ______________________________________________________________________________
# The following is for both MIRI and NIRSPEC
# grab the flux and DQ values for these pixles
            flux_all = input_model.data[y, x]
            dq_all = input_model.dq[y, x]
            valid2 = np.isfinite(flux_all)

            min_wave_tolerance = self.crval3 - np.absolute(self.zcoord[1] - self.zcoord[0])
            max_wave_tolerance = self.zcoord[-1] + np.absolute(self.zcoord[-1] - self.zcoord[-2])

            valid_min = np.where(wave >= min_wave_tolerance)
            not_mapped_low = wave.size - len(valid_min[0])

            valid_max = np.where(wave <= max_wave_tolerance)
            not_mapped_high = wave.size - len(valid_max[0])
            if not_mapped_low > 0:
                log.info('# of detector pixels not mapped to output plane: %i with wavelength below %f',
                         not_mapped_low, min_wave_tolerance)

            if not_mapped_high > 0:
                log.info('# of detector pixels not mapped to output plane: %i with wavelength above  %f',
                         not_mapped_high, max_wave_tolerance)

# ______________________________________________________________________________
# using the DQFlags from the input_image find pixels that should be excluded
# from the cube mapping
            all_flags = (dqflags.pixel['DO_NOT_USE'] +
                         dqflags.pixel['NON_SCIENCE'])

            valid3 = np.logical_and((wave >= min_wave_tolerance),
                                     (wave <= max_wave_tolerance))

            # find the location of all the values to reject in cube building
            good_data = np.where((np.bitwise_and(dq_all, all_flags) == 0) &
                                 (valid2) & (valid3))

            # good data holds the location of pixels we want to map to cube
            flux = flux_all[good_data]
            wave = wave[good_data]
            slice_no = slice_no[good_data]
            # based on the wavelength define the sroi, wroi, weight_power and
            # softrad to use in matching detector to spaxel values
            rois_det = np.zeros(wave.shape)
            roiw_det = np.zeros(wave.shape)
            weight_det = np.zeros(wave.shape)
            softrad_det = np.zeros(wave.shape)
            scalerad_det = np.zeros(wave.shape)

            if self.linear_wavelength:
                rois_det[:] = self.rois
                roiw_det[:] = self.roiw
                weight_det[:] = self.weight_power
                softrad_det[:] = self.soft_rad
                scalerad_det[:] = self.scalerad
            else:
                # for each wavelength find the closest point in the self.wavelength_table
                for iw, w in enumerate(wave):
                    ifound = (np.abs(self.wavelength_table - w)).argmin()
                    rois_det[iw] = self.rois_table[ifound]
                    roiw_det[iw] = self.roiw_table[ifound]
                    softrad_det[iw] = self.softrad_table[ifound]
                    weight_det[iw] = self.weight_power_table[ifound]
                    scalerad_det[iw] = self.scalerad_table[ifound]

            if self.coord_system == 'world':
                ra_use = ra[good_data]
                dec_use = dec[good_data]
                coord1, coord2 = coord.radec2std(self.crval1,
                                                 self.crval2,
                                                 ra_use, dec_use)

                if self.weighting == 'miripsf':
                    alpha_det = alpha[good_data]
                    beta_det = beta[good_data]
            elif self.coord_system == 'alpha-beta':
                coord1 = alpha[good_data]
                coord2 = beta[good_data]

        return coord1, coord2, wave, flux, slice_no, rois_det, roiw_det, weight_det, \
            softrad_det, scalerad_det, alpha_det, beta_det
# ********************************************************************************

    def map_fov_to_dqplane(self, this_par1, coord1, coord2, wave, roiw_ave, slice_no):
        """ Set an initial DQ flag for the IFU cube based on FOV of input data

        Map the FOV of channel (MIRI) or slice (NIRSPEC) to the DQ plane
        and set an initial DQ flagging. The process is different for MIRI and NIRSpec.
        In the MIRI case all the slices map roughly to the same FOV across the
        wavelength range covered by the IFU. This is not the case for NIRSpec the
        30 different slices map to different FOV on the range of wavelengths.

        Paramteter
        ---------
        this_par1: Channel (MIRI) or Grating (NIRSpec)
        coord1: xi coordinates of input data (~x coordinate in IFU space)
        coord2: eta coordinates of input data (~y coordinate in IFU space)
        wave: wavelength of input data
        roiw_ave: average spectral roi used to determine which wavelength bins
            the input values would be mapped to
        slice_no: integer slice value of input data (used in MIRI case to find
            the points of the edge slices.)
        """

        # MIRI mapping:
        # The FOV is roughtly the same for all the wavelength ranges.
        # The offset in the slices makes the calculation of the four corners
        # of the FOV more complicated. So we only use the two slices at
        # the edges of the FOV to define the 4 corners.
        # Note we can not use the wcs.footprint because this footprint only
        # consists of 4 values  ra min, ra max, dec min, dec max and we
        # need 4 corners made of 8 different values.

        if self.instrument == 'MIRI':

            # find the wavelength boundaries of the band - use two extreme slices
            wavemin = np.amin(wave)
            wavemax = np.amax(wave)

            # self.zcoord holds the center of the wavelength bin
            iwavemin = np.absolute(np.array(wavemin - self.zcoord) / self.cdelt3_normal)
            iwavemax = np.absolute(np.array(wavemax - self.zcoord) / self.cdelt3_normal)

            imin = np.where(iwavemin == np.amin(iwavemin))[0]
            imax = np.where(iwavemax == np.amin(iwavemax))[0]

            # for each wavelength plane - find the 2 extreme slices to set the FOV
            for w in range(imin[0], imax[0]):
                wave_distance = np.absolute(self.zcoord[w] - wave)

                # pull out the two extreme slices in the FOV.
                # use these points to set the FOV
                start_region = self.instrument_info.GetStartSlice(this_par1)
                end_region = self.instrument_info.GetEndSlice(this_par1)

                # if not wavelength dependent
                # coord1_start = coord1[slice == start_region]
                # coord2_start = coord2[slice == start_region]
                # coord1_end = coord1[slice == end_region]
                # coord2_end = coord2[slice == end_region]
                # wmin = imin[0]
                # wmax = imax[0]

                # the while loop should only be excuted 1 time if the slice matching
                # start_region is located in the data (default mode).

                istart = start_region
                coord1_start = None
                index_use = np.where((wave_distance < roiw_ave) & (slice_no == istart))
                if len(index_use[0]) > 0:
                    coord2_start = coord2[index_use]
                    coord1_start = coord1[index_use]

                iend = end_region
                coord1_end = None
                index_use = np.where((wave_distance < roiw_ave) & (slice_no == iend))
                if len(index_use[0]) > 0:
                    coord2_end = coord2[index_use]
                    coord1_end = coord1[index_use]

                # if there is valid data on this wavelength plane (not in a gap)
                if coord1_start is not None and coord1_end is not None:
                    coord1_total = np.concatenate((coord1_start, coord1_end), axis=0)
                    coord2_total = np.concatenate((coord2_start, coord2_end), axis=0)

                    # from an array of x and y values (contained in coord1_total and coord2_total)
                    # determine the footprint
                    footprint_all = self.four_corners(coord1_total, coord2_total)
                    isline, footprint = footprint_all

                    (xi1, eta1, xi2, eta2, xi3, eta3, xi4, eta4) = footprint

                    # find the overlap of FOV footprint and with IFU Cube
                    xi_corner = np.array([xi1, xi2, xi3, xi4])
                    eta_corner = np.array([eta1, eta2, eta3, eta4])
                    self.overlap_fov_with_spaxels(xi_corner, eta_corner, w, w)

        # NIRSpec Mapping:
        # The FOV of each NIRSpec slice varies across the wavelength range.
        # Each slice is mapped to each IFU wavelength plane
        # The FOV of the slice is really just a line, so instead of using
        # the routines the finds the overlap between a polygon and regular grid-
        # which is used for MIRI - an algorithm that determines the spaxels that
        # the slice line intersects is used instead.

        elif self.instrument == 'NIRSPEC':
            # for each of the 30 slices - find the projection of this slice
            # onto each of the IFU wavelength planes.
            for islice in range(30):
                index_slice = np.where(slice_no == islice+1)

                # find the smaller set of wavelengths to search over for this slice
                wavemin = np.amin(wave[index_slice])
                wavemax = np.amax(wave[index_slice])

                iwavemin = np.absolute(np.array(wavemin - self.zcoord) / (self.cdelt3_normal))
                iwavemax = np.absolute(np.array(wavemax - self.zcoord) / (self.cdelt3_normal))
                imin = np.where(iwavemin == np.amin(iwavemin))[0]
                imax = np.where(iwavemax == np.amin(iwavemax))[0]

                # loop over valid wavelengths for slice and find the projection of the
                # slice on  the wavelength plane

                for w in range(imin[0], imax[0]):
                    wave_distance = np.absolute(self.zcoord[w] - wave)
                    index_use = np.where((wave_distance < roiw_ave) & (slice_no == islice+1))
                    if len(index_use[0]) > 0:
                        coord2_use = coord2[index_use]
                        coord1_use = coord1[index_use]

                        footprint_all = self.four_corners(coord1_use, coord2_use)
                        isline, footprint = footprint_all

                        (xi1, eta1, xi2, eta2, xi3, eta3, xi4, eta4) = footprint
                        # find the overlap with IFU Cube
                        xi_corner = np.array([xi1, xi2, xi3, xi4])
                        eta_corner = np.array([eta1, eta2, eta3, eta4])
                        if isline:
                            self.overlap_slice_with_spaxels(xi_corner, eta_corner, w)
                        else:
                            self.overlap_fov_with_spaxels(xi_corner, eta_corner, w, w)

# ********************************************************************************

    def overlap_slice_with_spaxels(self, xi_corner, eta_corner, w):
        """ Set the initial dq plane of indicating if the input data falls on a spaxel

        This algorithm assumes the input data falls on a line in the IFU cube, which is
        the case for NIRSpec slices. The NIRSpec slice's endpoints are used to determine
        which IFU spaxels the slice falls on to set an initial dq flag.

        Parameters
        ---------
        xi_corner: holds the x starting and ending points of the slice
        eta_corner: holds the y starting and ending points of the slice
        wavelength: the wavelength bin of the IFU cube working with

        Sets
        ----
        self.spaxel_dq : numpy.ndarray containing intermediate dq flag

        """

        points = self.findpoints_on_slice(xi_corner, eta_corner)
        num = len(points)
        for i in range(num):
            xpt, ypt = points[i]
            index = (ypt * self.naxis1) + xpt
            self.spaxel_dq[w, index] = self.overlap_partial

# ********************************************************************************

    def findpoints_on_slice(self, xi_corner, eta_corner):
        """ Bresenham's Line Algorithm to find points a line intersects with grid.

        Given the endpoints of a line find the spaxels this line intersects.

        Parameters
        -----------
        xi_corner: holds the started in ending x values
        eta_corner: holds the started in ending y values


        Returns
        -------
        Points: a tuple of x,y spaxel values that this line intersects

        """

        # set up line - convert to integer values
        x1 = int((xi_corner[0] - self.xcoord[0])/self.cdelt1)
        y1 = int((eta_corner[0] - self.ycoord[0])/self.cdelt2)
        x2 = int((xi_corner[1] - self.xcoord[0])/self.cdelt1)
        y2 = int((eta_corner[1] - self.ycoord[0])/self.cdelt2)

        dx = x2 - x1
        dy = y2 - y1

        # how steep is it
        is_steep = abs(dy) > abs(dx)

        # Rotate line
        if is_steep:
            x1, y1 = y1, x1
            x2, y2 = y2, x2

        # Swap start and end points if necessary and store swap state
        swapped = False
        if x1 > x2:
            x1, x2 = x2, x1
            y1, y2 = y2, y1
            swapped = True

        # Recalculate differences
        dx = x2 - x1
        dy = y2 - y1

        # calculate error
        error = int(dx/2.0)
        ystep = -1
        if y1 < y2:
            ystep = 1

        # iterate over grid to generate points between the start and end of line
        y = y1
        points = []
        for x in range(x1, x2 + 1):
            coord = (y, x) if is_steep else (x, y)
            points.append(coord)
            error -= abs(dy)
            if error < 0:
                y += ystep
                error += dx

        # If coords were swapped then reverse
        if swapped:
            points.reverse()
        return points
# ********************************************************************************

    def overlap_fov_with_spaxels(self, xi_corner, eta_corner, wmin, wmax):

        """find the amount of overlap of FOV with each spaxel

        Given the corners of the FOV  find the spaxels that
        overlap with this FOV.  Set the intermediate spaxel  to
        a value based on the overlap between the FOV for each exposure
        and the spaxel area. The values assigned are:
        a. self.overlap_partial = overlap partial
        b  self.overlap_full = overlap_full
        bit_wise combination of these values is allowed to account for
        dithered FOVs.

        Parameter
        ----------
        xi_corner: xi coordinates of the 4 corners of the FOV on the cube plane
        eta_corner: eta coordinates of the 4 corners of the FOV on the cube plane
        wmin: minimum wavelength bin in the IFU cube that this data covers
        wmax: maximum wavelength bin in the IFU cube that this data covers

        Sets
        -------
        self.spaxel_dq : numpy.ndarray containing intermediate dq flag

        """

        # ximin = np.amin(xi_corner)
        # ximax = np.amax(xi_corner)
        # etamin = np.amin(eta_corner)
        # etamax = np.amax(eta_corner)
        # index = np.where((self.xcenters > ximin) & (self.xcenters < ximax) &
        #                  (self.ycenters > etamin) & (self.ycenters < etamax))

        wave_slice_dq = np.zeros(self.naxis2 * self.naxis1, dtype=np.int32)
        # loop over spaxels in the spatial plane and set slice_dq
        nxy = self.xcenters.size  # size of spatial plane
        for ixy in range(nxy):
            area_box = self.cdelt1 * self.cdelt2
            area_overlap = cube_overlap.sh_find_overlap(self.xcenters[ixy],
                                                        self.ycenters[ixy],
                                                        self.cdelt1, self.cdelt2,
                                                        xi_corner, eta_corner)

            overlap_coverage = area_overlap/area_box
            if overlap_coverage > self.tolerance_dq_overlap:
                if overlap_coverage > 0.95:
                    wave_slice_dq[ixy] = self.overlap_full
                else:
                    wave_slice_dq[ixy] = self.overlap_partial

        # set for a range of wavelengths
        if wmin != wmax:
            self.spaxel_dq[wmin:wmax, :] = np.bitwise_or(self.spaxel_dq[wmin:wmax, :],
                                                        wave_slice_dq)

        # set for a single wavelength
        else:
            self.spaxel_dq[wmin, :] = np.bitwise_or(self.spaxel_dq[wmin, :],
                                                   wave_slice_dq)
# *******************************************************************************

    def four_corners(self, coord1, coord2):
        """ helper function to compute the four corners of the FOV

        From an array of x and y values find the 4 corners enclosing these points
        This routine defines the four corners as
        corner 1: location of min coord2
        corner 2: location of min coord1
        corner 3: location of max coord2
        corner 4: location of max coord1

        Parameter
        ----------
        coord1: array of 4 x corners
        coord2: array of 4 y corners

        Returns
        -------
        Footprint of 4 corners
        Is the data contained in coor1 and coord2 represented by a line if yes:
          isline = True if not isline = False

        """

        isline = False
        index = np.where(coord2 == np.amin(coord2))
        xi_corner1 = coord1[index[0]]
        eta_corner1 = coord2[index[0]]

        index = np.where(coord1 == np.amax(coord1))
        xi_corner2 = coord1[index[0]]
        eta_corner2 = coord2[index[0]]

        index = np.where(coord2 == np.amax(coord2))
        xi_corner3 = coord1[index[0]]
        eta_corner3 = coord2[index[0]]

        index = np.where(coord1 == np.amin(coord1))
        xi_corner4 = coord1[index[0]]
        eta_corner4 = coord2[index[0]]
        footprint = (xi_corner1[0], eta_corner1[0],
                     xi_corner2[0], eta_corner2[0],
                     xi_corner3[0], eta_corner3[0],
                     xi_corner4[0], eta_corner4[0])

        distance_min_points = math.sqrt((xi_corner1 - xi_corner4)**2 +
                                        (eta_corner1 - eta_corner4)**2)

        distance_max_points = math.sqrt((xi_corner2 - xi_corner3)**2 +
                                        (eta_corner2 - eta_corner3)**2)
        dist_tolerance = 0.0001  # tolerance used if points fall on a line
        if ((distance_min_points < dist_tolerance) and
            (distance_max_points < dist_tolerance)):
            isline = True
        footprint_all = (isline, footprint)

        return footprint_all
# ********************************************************************************

    def find_spaxel_flux(self):

        """Depending on the interpolation method, find the flux for each spaxel value
        """
# currently these are the same but in the future there could be a difference in
# how the spaxel flux is determined according to self.interpolation.

        if self.interpolation == 'area':
            good = self.spaxel_iflux > 0
            self.spaxel_flux[good] = self.spaxel_flux[good] / self.spaxel_weight[good]
        elif self.interpolation == 'pointcloud':
            good = self.spaxel_iflux > 0
            self.spaxel_flux[good] = self.spaxel_flux[good] / self.spaxel_weight[good]
# ********************************************************************************

    def set_final_dq_flags(self):

        """ Set up the final dq flags, Good data(0) , NON_SCIENCE or DO_NOT_USE
        """

        # An initial set of dq flags was set in overlap_fov_with_spaxel or
        # overlap_slice_with_spaxel. The initial dq dlags are defined in ifu_cube
        # class:
        # self.overlap_partial = 4  # intermediate flag
        # self.overlap_full  = 2    # intermediate flag
        # self.overlap_hole = dqflags.pixel['DO_NOT_USE']
        # self.overlap_no_coverage = dqflags.pixel['NON_SCIENCE'] (also bitwise and with
        # dqflags.pixel['DO_NOT_USE'] )

        # compare the weight plane and spaxel_dq. The initial spaxel_dq flagging
        # has too small a FOV in NIRSpec line mapping case.

        # flatten to match the size of spaxel_weight
        self.spaxel_dq = np.ndarray.flatten(self.spaxel_dq)

        # the fov is an underestimate. Check the spaxel_weight plane
        # if weight map > 0 then set spaxel_dq to overlap_partial
        under_data = self.spaxel_weight > 0
        self.spaxel_dq[under_data] = self.overlap_partial

        # convert all remaining spaxel_dq of 0 to NON_SCIENCE + DO_NOT_USE
        # these pixel should have no overlap with the data
        non_science = self.spaxel_dq == 0
        self.spaxel_dq[non_science] = np.bitwise_or(self.overlap_no_coverage,
                                                    dqflags.pixel['DO_NOT_USE'])

        # refine where good data should be
        ind_full = np.where(np.bitwise_and(self.spaxel_dq, self.overlap_full))
        ind_partial = np.where(np.bitwise_and(self.spaxel_dq, self.overlap_partial))

        self.spaxel_dq[ind_full] = 0
        self.spaxel_dq[ind_partial] = 0

        location_holes = np.where((self.spaxel_dq == 0) & (self.spaxel_weight == 0))
        self.spaxel_dq[location_holes] = self.overlap_hole

        # one last check. Remove pixels flagged as hole but have 1 adjacent spaxel
        # that has no coverage (NON_SCIENCE).  If NON_SCIENCE flag is next to pixel
        # flagged as hole then set the Hole flag to NON_SCIENCE
        spaxel_dq_temp = self.spaxel_dq
        nxy = self.naxis1 * self.naxis2
        index = np.where(self.spaxel_dq == self.overlap_hole)
        for i in range(len(index[0])):
            iwave = int(index[0][i]/nxy)
            rem = index[0][i] - iwave*nxy
            yrem = int(rem/self.naxis1)
            xrem = rem - yrem * self.naxis1

            found = 0
            ij = 0
            # do not allow holes to occur at the edge of IFU cube
            if (yrem == 0 or yrem == (self.naxis2-1) or
                xrem == 0 or xrem == (self.naxis1-1)):
                spaxel_dq_temp[index[0][i]] = np.bitwise_or(self.overlap_no_coverage,
                                                            dqflags.pixel['DO_NOT_USE'])
                found = 1
            # flag as NON_SCIENCE instead of hole if left, right, top, bottom pixel
            # is NON_SCIENCE
            xcheck = np.zeros(4, dtype=int)
            ycheck = np.zeros(4, dtype=int)
            # left
            xcheck[0] = xrem - 1
            ycheck[0] = yrem
            # right
            xcheck[1] = xrem + 1
            ycheck[1] = yrem
            # bottom
            xcheck[2] = xrem
            ycheck[2] = yrem - 1
            # top
            xcheck[3] = xrem
            ycheck[3] = yrem + 1

            while ((ij < 4) and (found == 0)):
                if(xcheck[ij] > 0 and xcheck[ij] < self.naxis1 and
                   ycheck[ij] > 0 and ycheck[ij] < self.naxis2):
                    index_check = iwave*nxy + ycheck[ij]*self.naxis1 + xcheck[ij]
                    # If the nearby spaxel_dq contains overlap_no_covrage
                    # then unmark dq flag as hole. A hole has to have nearby
                    # pixels all in FOV.
                    check = (np.bitwise_and(self.spaxel_dq[index_check],
                                            self.overlap_no_coverage) == self.overlap_no_coverage)
                    if check:
                        spaxel_dq_temp[index[0][i]] = np.bitwise_or(self.overlap_no_coverage,
                                                                    dqflags.pixel['DO_NOT_USE'])
                        found = 1
                ij = ij + 1

        self.spaxel_dq = spaxel_dq_temp
        location_holes = np.where(self.spaxel_dq == self.overlap_hole)
        ave_holes = len(location_holes[0])/self.naxis3

        if ave_holes < 1:
            log.info('Average # of holes/wavelength plane is < 1')
        else:
            log.info('Average # of holes/wavelength plane: %i', ave_holes)
        log.info('Total # of holes for IFU cube is : %i', len(location_holes[0]))

# ********************************************************************************

    def setup_final_ifucube_model(self, j):

        """ Set up the final meta WCS info of IFUCube along with other fits keywords

        return IFUCube model

        """
        naxis1 = self.naxis1
        naxis2 = self.naxis2
        naxis3 = self.naxis3

        data = np.zeros((naxis3, naxis2, naxis1))
        idata = np.zeros((naxis3, naxis2, naxis1))
        dq_cube = np.zeros((naxis3, naxis2, naxis1))
        err_cube = np.zeros((naxis3, naxis2, naxis1))

        if self.linear_wavelength:
            ifucube_model = datamodels.IFUCubeModel(data=data, dq=dq_cube,
                                                    err=err_cube,
                                                    weightmap=idata)
        else:
            wave = np.asarray(self.wavelength_table, dtype=np.float32)
            num = len(wave)
            alldata = np.array(
                [(wave[None].T, )],
                dtype=[('wavelength', '<f4', (num, 1))]
            )

            ifucube_model = datamodels.IFUCubeModel(data=data, dq=dq_cube,
                                                    err=err_cube,
                                                    weightmap=idata,
                                                    wavetable=alldata)

        ifucube_model.update(self.input_models[j])
        ifucube_model.meta.filename = self.output_name

        # Call model_blender if there are multiple inputs
        if len(self.input_models) > 1:
            saved_model_type = ifucube_model.meta.model_type
            self.blend_output_metadata(ifucube_model)
            # Reset to original
            ifucube_model.meta.model_type = saved_model_type
# ______________________________________________________________________
        if self.output_type == 'single':
            with datamodels.open(self.input_models[j]) as input:
                # define the cubename for each single
                filename = self.input_filenames[j]
                indx = filename.rfind('.fits')
                self.output_name_base = filename[:indx]
                self.output_file = None
                newname = self.define_cubename()
                ifucube_model.meta.filename = newname
# ______________________________________________________________________
# fill in Channel for MIRI
        if self.instrument == 'MIRI':
            # fill in Channel output meta data
            num_ch = len(self.list_par1)
            outchannel = self.list_par1[0]
            for m in range(1, num_ch):
                outchannel = outchannel + str(self.list_par1[m])

            outchannel = "".join(set(outchannel))
            outchannel = "".join(sorted(outchannel))
            ifucube_model.meta.instrument.channel = outchannel
            log.info('IFUChannel %s', ifucube_model.meta.instrument.channel)
# ______________________________________________________________________
        ifucube_model.meta.wcsinfo.crval1 = self.crval1
        ifucube_model.meta.wcsinfo.crval2 = self.crval2
        ifucube_model.meta.wcsinfo.crpix1 = self.crpix1
        ifucube_model.meta.wcsinfo.crpix2 = self.crpix2

        ifucube_model.meta.wcsinfo.cdelt1 = self.cdelt1 / 3600.0
        ifucube_model.meta.wcsinfo.cdelt2 = self.cdelt2 / 3600.0
        if self.linear_wavelength:
            ifucube_model.meta.wcsinfo.crval3 = self.crval3
            ifucube_model.meta.wcsinfo.cdelt3 = self.cdelt3
            ifucube_model.meta.wcsinfo.ctype3 = 'WAVE'
            ifucube_model.meta.wcsinfo.crpix3 = self.crpix3
            ifucube_model.meta.ifu.roi_spatial = float(self.rois)
            ifucube_model.meta.ifu.roi_wave = float(self.roiw)
        else:
            ifucube_model.meta.wcsinfo.ctype3 = 'WAVE-TAB'
            ifucube_model.meta.wcsinfo.ps3_0 = 'WCS-TABLE'
            ifucube_model.meta.wcsinfo.ps3_1 = 'wavelength'
            ifucube_model.meta.wcsinfo.crval3 = 1.0
            ifucube_model.meta.wcsinfo.crpix3 = 1.0
            ifucube_model.meta.wcsinfo.cdelt3 = None
            ifucube_model.meta.ifu.roi_wave = np.mean(self.roiw_table)
            ifucube_model.wavedim = '(1,{:d})'.format(num)

        ifucube_model.meta.wcsinfo.ctype1 = 'RA---TAN'
        ifucube_model.meta.wcsinfo.ctype2 = 'DEC--TAN'
        ifucube_model.meta.wcsinfo.cunit1 = 'deg'
        ifucube_model.meta.wcsinfo.cunit2 = 'deg'

        ifucube_model.meta.wcsinfo.cunit3 = 'um'
        ifucube_model.meta.wcsinfo.wcsaxes = 3
        ifucube_model.meta.wcsinfo.pc1_1 = -1
        ifucube_model.meta.wcsinfo.pc1_2 = 0
        ifucube_model.meta.wcsinfo.pc1_3 = 0

        ifucube_model.meta.wcsinfo.pc2_1 = 0
        ifucube_model.meta.wcsinfo.pc2_2 = 1
        ifucube_model.meta.wcsinfo.pc2_3 = 0

        ifucube_model.meta.wcsinfo.pc3_1 = 0
        ifucube_model.meta.wcsinfo.pc3_2 = 0
        ifucube_model.meta.wcsinfo.pc3_3 = 1

        ifucube_model.meta.ifu.flux_extension = 'SCI'
        ifucube_model.meta.ifu.error_extension = 'ERR'
        ifucube_model.meta.ifu.error_type = 'ERR'
        ifucube_model.meta.ifu.dq_extension = 'DQ'
        ifucube_model.meta.ifu.weighting = str(self.weighting)

        # weight_power is needed for single cubes. Linear Wavelengths
        # if non-linear wavelengths then this will be None
        ifucube_model.meta.ifu.weight_power = self.weight_power

        with datamodels.open(self.input_models[j]) as input:
            ifucube_model.meta.bunit_data = input.meta.bunit_data
            ifucube_model.meta.bunit_err = input.meta.bunit_err

        if self.coord_system == 'alpha-beta':
            ifucube_model.meta.wcsinfo.cunit1 = 'arcsec'
            ifucube_model.meta.wcsinfo.cunit2 = 'arcsec'

# we only need to check list_par1[0] and list_par2[0] because these types
# of cubes are made from 1 exposures (setup_cube checks this at the start
# of cube_build).
            if self.list_par1[0] == '1' and self.list_par2[0] == 'short':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL1A'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE1A'
            if self.list_par1[0] == '2' and self.list_par2[0] == 'short':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL2A'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE2A'
            if self.list_par1[0] == '3' and self.list_par2[0] == 'short':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL3A'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE3A'
            if self.list_par1[0] == '4' and self.list_par2[0] == 'short':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL4A'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE4A'

            if self.list_par1[0] == '1' and self.list_par2[0] == 'medium':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL1B'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE1B'
            if self.list_par1[0] == '2' and self.list_par2[0] == 'medium':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL2B'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE2B'
            if self.list_par1[0] == '3' and self.list_par2[0] == 'medium':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL3B'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE3B'
            if self.list_par1[0] == '4' and self.list_par2[0] == 'medium':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL4B'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE4B'

            if self.list_par1[0] == '1' and self.list_par2[0] == 'long':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL1C'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE1C'
            if self.list_par1[0] == '2' and self.list_par2[0] == 'long':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL2C'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE2C'
            if self.list_par1[0] == '3' and self.list_par2[0] == 'long':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL3C'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE3C'
            if self.list_par1[0] == '4' and self.list_par2[0] == 'long':
                ifucube_model.meta.wcsinfo.ctype1 = 'MRSAL4C'
                ifucube_model.meta.wcsinfo.ctype2 = 'MRSBE4C'

# set WCS information
        wcsobj = pointing.create_fitswcs(ifucube_model)
        ifucube_model.meta.wcs = wcsobj
        ifucube_model.meta.wcs.bounding_box = ((0, naxis1 - 1),
                                               (0, naxis2 - 1),
                                               (0, naxis3 - 1))

        return ifucube_model
# ********************************************************************************

    def update_ifucube(self, ifucube_model):
        """ Fill in the ifucube_model and run fits blender

        Parameters
        ----------
        ifucube_model: datamodel
          final ifucube data model

        Returns
        -------
        fills in ifucube_model arrays using spaxel arrays
        """
    # pull out data into array and assign to ifucube data model
        temp_flux = self.spaxel_flux.reshape((self.naxis3,
                                              self.naxis2, self.naxis1))
        temp_wmap = self.spaxel_iflux.reshape((self.naxis3,
                                               self.naxis2, self.naxis1))

        temp_dq = self.spaxel_dq.reshape((self.naxis3,
                                          self.naxis2, self.naxis1))

        ifucube_model.data = temp_flux
        ifucube_model.weightmap = temp_wmap
        ifucube_model.dq = temp_dq
        ifucube_model.meta.cal_step.cube_build = 'COMPLETE'

# ***************************************************************************

    def blend_output_metadata(self, IFUCube):

        """Create new output metadata based on blending all input metadata."""
        # Run fitsblender on output product
        output_file = IFUCube.meta.filename
        blendmeta.blendmodels(IFUCube, inputs=self.input_models,
                              output=output_file)


class IncorrectInput(Exception):
    """ Raises an exception if input parameter, Interpolation, is set to area
    when more than one file is used to build the cube.
    """
    pass


class AreaInterpolation(Exception):
    """ Raises an exception if input parameter, Interpolation, is set to area
    and the input parameter of the spatial scale of second dimension of cube
    is also set.
    """
    pass
