from collections import defaultdict
import os.path as op
import traceback

from .. import datamodels
from ..assign_wcs.util import NoDataOnDetectorError
from ..lib.pipe_utils import is_tso
from ..stpipe import Pipeline

# step imports
from ..assign_wcs import assign_wcs_step
from ..background import background_step
from ..imprint import imprint_step
from ..msaflagopen import msaflagopen_step
from ..extract_2d import extract_2d_step
from ..flatfield import flat_field_step
from ..srctype import srctype_step
from ..straylight import straylight_step
from ..fringe import fringe_step
from ..pathloss import pathloss_step
from ..barshadow import barshadow_step
from ..photom import photom_step
from ..cube_build import cube_build_step
from ..extract_1d import extract_1d_step
from ..resample import resample_spec_step

__all__ = ['Spec2Pipeline']


class Spec2Pipeline(Pipeline):
    """
    Spec2Pipeline: Processes JWST spectroscopic exposures from Level 2a to 2b.
    Accepts a single exposure or an association as input.

    Included steps are:
    assign_wcs, background subtraction, NIRSpec MSA imprint subtraction,
    NIRSpec MSA bad shutter flagging, 2-D subwindow extraction, flat field,
    source type decision, straylight, fringe, pathloss, barshadow,  photom,
    resample_spec, cube_build, and extract_1d.
    """

    spec = """
        save_bsub = boolean(default=False)        # Save background-subracted science
        fail_on_exception = boolean(default=True) # Fail if any product fails.
    """

    # Define aliases to steps
    step_defs = {
        'bkg_subtract': background_step.BackgroundStep,
        'assign_wcs': assign_wcs_step.AssignWcsStep,
        'imprint_subtract': imprint_step.ImprintStep,
        'msa_flagging': msaflagopen_step.MSAFlagOpenStep,
        'extract_2d': extract_2d_step.Extract2dStep,
        'flat_field': flat_field_step.FlatFieldStep,
        'srctype': srctype_step.SourceTypeStep,
        'straylight': straylight_step.StraylightStep,
        'fringe': fringe_step.FringeStep,
        'pathloss': pathloss_step.PathLossStep,
        'barshadow': barshadow_step.BarShadowStep,
        'photom': photom_step.PhotomStep,
        'resample_spec': resample_spec_step.ResampleSpecStep,
        'cube_build': cube_build_step.CubeBuildStep,
        'extract_1d': extract_1d_step.Extract1dStep
    }

    # Main processing
    def process(self, input):
        """Entrypoint for this pipeline

        Parameters
        ----------
        input: str, Level2 Association, or DataModel
            The exposure or association of exposures to process
        """
        self.log.info('Starting calwebb_spec2 ...')

        # Retrieve the input(s)
        asn = self.load_as_level2_asn(input)

        # Each exposure is a product in the association.
        # Process each exposure.
        results = []
        has_exceptions = False
        for product in asn['products']:
            self.log.info('Processing product {}'.format(product['name']))
            self.output_file = product['name']
            try:
                getattr(asn, 'filename')
            except AttributeError:
                asn.filename = "singleton"
            try:
                result = self.process_exposure_product(
                    product,
                    asn['asn_pool'],
                    asn.filename
                )
            except NoDataOnDetectorError as exception:
                # This error merits a special return
                # status if run from the command line.
                # Bump it up now.
                raise exception
            except Exception:
                traceback.print_exc()
                has_exceptions = True
            else:
                if result is not None:
                    results.append(result)

        if has_exceptions and self.fail_on_exception:
            raise RuntimeError(
                'One or more products failed to process. Failing calibration.'
            )

        # We're done
        self.log.info('Ending calwebb_spec2')

        self.output_use_model = True
        self.suffix = False
        return results

    # Process each exposure
    def process_exposure_product(
            self,
            exp_product,
            pool_name=' ',
            asn_file=' '
    ):
        """Process an exposure found in the association product

        Parameters
        ---------
        exp_product: dict
            A Level2b association product.
        """

        # Find all the member types in the product
        members_by_type = defaultdict(list)
        for member in exp_product['members']:
            members_by_type[member['exptype'].lower()].append(member['expname'])

        # Get the science member. Technically there should only be
        # one. We'll just get the first one found.
        science = members_by_type['science']
        if len(science) != 1:
            self.log.warning(
                'Wrong number of science exposures found in {}'.format(
                    exp_product['name']
                )
            )
            self.log.warning('    Using only first one.')
        science = science[0]

        self.log.info('Working on input %s ...', science)
        input = self.open_model(science)
        exp_type = input.meta.exposure.type
        tso_mode = is_tso(input)

        WFSS_TYPES = ["NIS_WFSS", "NRC_WFSS"]

        # Apply WCS info
        # check the datamodel to see if it's
        # a grism image, if so get the catalog
        # name from the asn and record it to the meta
        if exp_type in WFSS_TYPES:
            try:
                input.meta.source_catalog.filename = members_by_type['sourcecat'][0]
                self.log.info('Using sourcecat file {}'.format(input.meta.source_catalog.filename))
            except IndexError:
                if input.meta.source_catalog.filename is None:
                    raise IndexError("No source catalog specified in association or datamodel")

        assign_wcs_exception = None
        try:
            input = self.assign_wcs(input)
        except Exception as exception:
            assign_wcs_exception = exception

        # If assign_wcs was skipped, abort the rest of processing,
        # because so many downstream steps depend on the WCS
        if assign_wcs_exception is not None or \
           input.meta.cal_step.assign_wcs != 'COMPLETE':
            message = (
                'Assign_wcs processing was skipped.'
                '\nAborting remaining processing for this exposure.'
                '\nNo output product will be created.'
            )
            if self.assign_wcs.skip:
                self.log.warning(message)
                return
            else:
                self.log.error(message)
                if assign_wcs_exception is not None:
                    raise assign_wcs_exception
                else:
                    raise RuntimeError('Cannot determine WCS.')

        # Do background processing, if necessary
        if exp_type in WFSS_TYPES or len(members_by_type['background']) > 0:

            if exp_type in WFSS_TYPES:
                bkg_list = []           # will be overwritten by the step
            else:
                bkg_list = members_by_type['background']

            # Setup for saving
            self.bkg_subtract.suffix = 'bsub'
            if isinstance(input, datamodels.CubeModel):
                self.bkg_subtract.suffix = 'bsubints'

            # Backwards compatibility
            if self.save_bsub:
                self.bkg_subtract.save_results = True

            # Call the background subtraction step
            input = self.bkg_subtract(input, bkg_list)

        # Apply NIRSpec MSA imprint subtraction
        # Technically there should be just one.
        # We'll just get the first one found
        imprint = members_by_type['imprint']
        if exp_type in ['NRS_MSASPEC', 'NRS_IFU'] and \
           len(imprint) > 0:
            if len(imprint) > 1:
                self.log.warning('Wrong number of imprint members')
            imprint = imprint[0]
            input = self.imprint_subtract(input, imprint)

        # Apply NIRSpec MSA bad shutter flagging
        if exp_type in ['NRS_MSASPEC', 'NRS_IFU']:
            input = self.msa_flagging(input)

        # This makes it clear that flat_field
        # should be done before extract_2d for all WFSS/GRISM data.
        if exp_type in ['NRC_WFSS', 'NIS_WFSS', 'NRC_TSGRISM']:
            # Apply flat-field correction
            input = self.flat_field(input)
            input = self.extract_2d(input)
        else:
            # Extract 2D sub-windows for NIRSpec slit and MSA
            if exp_type in ['NRS_FIXEDSLIT', 'NRS_BRIGHTOBJ', 'NRS_MSASPEC', 'NRS_LAMP']:
                input = self.extract_2d(input)

            # Apply flat-field correction
            input = self.flat_field(input)

        # Apply the source type decision step
        input = self.srctype(input)

        # Apply the straylight correction for MIRI MRS
        if exp_type == 'MIR_MRS':
            input = self.straylight(input)

        # Apply the fringe correction for MIRI MRS
        if exp_type == 'MIR_MRS':
            input = self.fringe(input)

        # Apply pathloss correction to NIRSpec and NIRISS SOSS exposures
        if exp_type in ['NRS_FIXEDSLIT', 'NRS_MSASPEC', 'NRS_IFU', 'NIS_SOSS']:
            input = self.pathloss(input)

        # Apply barshadow correction to NIRSPEC MSA exposures
        if exp_type == 'NRS_MSASPEC':
            input = self.barshadow(input)

        # Apply flux calibration
        result = self.photom(input)

        # Record ASN pool and table names in output
        result.meta.asn.pool_name = pool_name
        result.meta.asn.table_name = op.basename(asn_file)

        # Setup to save the calibrated exposure at end of step.
        if tso_mode:
            suffix = 'calints'
        else:
            suffix = 'cal'
        result.meta.filename = self.make_output_path(suffix=suffix)

        # Produce a resampled product, either via resample_spec for
        # "regular" spectra or cube_build for IFU data. No resampled
        # product is produced for time-series modes.
        if exp_type in ['NRS_FIXEDSLIT', 'NRS_MSASPEC', 'MIR_LRS-FIXEDSLIT'] \
        and not isinstance(result, datamodels.CubeModel):

            # Call the resample_spec step for 2D slit data
            self.resample_spec.suffix = 's2d'
            result_extra = self.resample_spec(result)

        elif exp_type in ['MIR_MRS', 'NRS_IFU']:

            # Call the cube_build step for IFU data;
            # always create a single cube containing multiple
            # wavelength bands
            self.cube_build.output_type = 'multi'
            self.cube_build.save_results = False
            result_extra = self.cube_build(result)
            if not self.cube_build.skip:
                self.save_model(result_extra[0], 's3d')
        else:
            result_extra = result

        # Extract a 1D spectrum from the 2D/3D data
        if tso_mode:
            self.extract_1d.suffix = 'x1dints'
        else:
            self.extract_1d.suffix = 'x1d'
        x1d_result = self.extract_1d(result_extra)

        result_extra.close()
        x1d_result.close()

        # That's all folks
        self.log.info(
            'Finished processing product {}'.format(exp_product['name'])
        )

        return result
