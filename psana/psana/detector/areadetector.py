"""
Data access methods common for all AREA DETECTORS
=================================================

Usage::

  from psana.detector.areadetector import AreaDetector

  o = AreaDetector(*args, **kwa) # inherits from DetectorImpl(*args, **kwa)

  a = o.raw(evt)
  a = o._segment_numbers(evt)
  a = o._det_calibconst()

  a = o._pedestals()
  a = o._gain()
  a = o._rms()
  a = o._status()
  a = o._mask_calib()
  a = o._common_mode()
  a = o._det_geotxt_and_meta()
  a = o._det_geotxt_default()
  a = o._det_geo()
  a = o._pixel_coord_indexes(pix_scale_size_um=None, xy0_off_pix=None, do_tilt=True, cframe=0, **kwa)
  a = o._pixel_coords(do_tilt=True, cframe=0, **kwa)
  a = o._cached_pixel_coord_indexes(evt, **kwa) # **kwa - the same as above

  a = o._shape_as_daq()
  a = o._number_of_segments_total()

  a = o._mask_default(dtype=DTYPE_MASK)
  a = o._mask_calib()
  a = o._mask_calib_or_default(dtype=DTYPE_MASK)
  a = o._mask_from_status(status_bits=0xffff, dtype=DTYPE_MASK, **kwa) # gain_range_inds=(0,1,2,3,4) - gain ranges to merge for apropriate detectors
  a = o._mask_neighbors(mask, rad=9, ptrn='r')
  a = o._mask_edges(width=0, edge_rows=1, edge_cols=1, dtype=DTYPE_MASK, **kwa)
  a = o._mask_center(wcenter=0, center_rows=1, center_cols=1, dtype=DTYPE_MASK, **kwa)
  a = o._mask_comb(**kwa) # the same as _mask but w/o caching
  a = o._mask(status=True, status_bits=0xffff, gain_range_inds=(0,1,2,3,4),\
              neighbors=False, rad=3, ptrn='r',\
              edges=True, width=0, edge_rows=10, edge_cols=5,\
              center=True, wcenter=0, center_rows=5, center_cols=3,\
              calib=False,\
              umask=None,\
              force_update=False)

  a = o.calib(evt, cmpars=(7,2,100,10), *kwargs)
  a = o.calib(evt, **kwa)
  a = o.image(self, evt, nda=None, **kwa)

2020-11-06 created by Mikhail Dubrovin
"""

from psana.detector.detector_impl import DetectorImpl

import logging
logger = logging.getLogger(__name__)

import numpy as np

from psana.detector.calibconstants import CalibConstants

from psana.pscalib.geometry.SegGeometryStore import sgs
#from psana.pscalib.geometry.GeometryAccess import GeometryAccess #, img_from_pixel_arrays
from psana.detector.NDArrUtils import info_ndarr, reshape_to_3d # print_ndarr,shape_as_2d, shape_as_3d, reshape_to_2d
from psana.detector.UtilsAreaDetector import arr3d_from_dict,\
        img_from_pixel_arrays, img_multipixel_max, img_multipixel_mean,\
        img_interpolated, fill_holes

import psana.detector.Utils as ut
is_none = ut.is_none


#import psana.detector.UtilsMask as um
#DTYPE_MASK, DTYPE_STATUS = um.DTYPE_MASK, um.DTYPE_STATUS
from psana.detector.mask_algos import MaskAlgos, DTYPE_MASK, DTYPE_STATUS


from amitypes import Array2d, Array3d


class AreaDetector(DetectorImpl):

    def __init__(self, *args, **kwargs):
        logger.debug('AreaDetector.__init__') #  self.__class__.__name__
        DetectorImpl.__init__(self, *args, **kwargs)

        self._calibc_ = None
        self._maskalgos_ = None


    def raw(self,evt) -> Array3d:
        """
        Returns dense 3-d numpy array of segment data
        from dict self._segments(evt)

        Parameters
        ----------
        evt: event
            psana event object, ex. run.events().next().

        Returns
        -------
        raw data: np.array, ndim=3, shape: as data
        """
        if evt is None: return None
        segs = self._segments(evt)
        if is_none(segs, 'self._segments(evt) is None'): return None
        return arr3d_from_dict({k:v.raw for k,v in segs.items()})


    def _segment_numbers(self,evt):
        """ Returns dense 1-d numpy array of segment indexes.
        from dict self._segments(evt)
        """
        segs = self._segments(evt)
        if is_none(segs, 'self._segments(evt) is None'): return None
        return np.array(sorted(segs.keys()), dtype=np.uint16)


    def _maskalgos(self, **kwa):
        if self._maskalgos_ is None:
            logger.debug('AreaDetector._maskalgos - make MaskAlgos')
            cc = self._calibconst
            if is_none(cc, 'self._calibconst is None'): return None
            self._maskalgos_ = MaskAlgos(cc, **kwa)
        return self._maskalgos_


    def _calibconstants(self, **kwa):
        if self._calibc_ is None:
            logger.debug('AreaDetector._calibconstants - make CalibConstants')
            cc = self._calibconst
            if is_none(cc, 'self._calibconst is None'): return None
            self._calibc_ = CalibConstants(cc, **kwa)
        return self._calibc_


    def _det_calibconst(self, metname, **kwa):
        logger.debug('AreaDetector._det_calibconst')
        o = self._calibconstants(**kwa)
        return None if o is None else getattr(o, metname)()


    def _det_calibconst_kwa(self, metname, **kwa):
        logger.debug('AreaDetector._det_calibconst_kwa')
        o = self._calibconstants(**kwa)
        return None if o is None else getattr(o, metname)(**kwa)


    def _pedestals(self):   return self._det_calibconst('pedestals')
    def _rms(self):         return self._det_calibconst('rms')
    def _status(self):      return self._det_calibconst('status')
    def _mask_calib(self):  return self._det_calibconst('mask_calib')
    def _common_mode(self): return self._det_calibconst('common_mode')
    def _gain(self):        return self._det_calibconst('gain')
    def _gain_factor(self): return self._det_calibconst('gain_factor')

    def _det_geotxt_and_meta(self): return self._det_calibconst('geotxt_and_meta')
    def _det_geotxt_default(self):  return self._det_calibconst('geotxt_default')
    def _det_geo(self):             return self._det_calibconst('geo')

    def _pixel_coord_indexes(self, **kwa): return self._det_calibconst_kwa('pixel_coord_indexes', **kwa)

    def _pixel_coords(self, **kwa): return self._det_calibconst_kwa('pixel_coords', **kwa)

    def _shape_as_daq(self): return self._det_calibconst('shape_as_daq')

    def _number_of_segments_total(self): return self._det_calibconst('number_of_segments_total')

    def _cached_pixel_coord_indexes(self, evt, **kwa):
        """
        """
        logger.debug('AreaDetector._cached_pixel_coord_indexes')
        kwa['segnums'] = self._segment_numbers(evt)
        logger.debug('segnums: %s' % str(kwa['segnums']))
        return self._det_calibconst_kwa('cached_pixel_coord_indexes', **kwa)

    def _cached_pix_rc(self): return self._det_calibconst('pix_rc')

    def _cached_pix_xyz(self): return self._det_calibconst('pix_xyz')

    def _cached_interpol_pars(self): return self._det_calibconst('interpol_pars')


    def calib(self, evt, **kwa) -> Array3d:
        """
        """
        logger.debug('%s.calib(evt) is implemented for generic case of area detector as raw - pedestals' % self.__class__.__name__\
                      +'\n  If needed more, it needs to be re-implemented for this detector type.')
        raw = self.raw(evt)
        if is_none(raw, 'det.raw.raw(evt) is None'): return None

        peds = self._pedestals()
        if is_none(peds, 'det.raw._pedestals() is None - return det.raw.raw(evt)'): return raw

        arr = raw - peds
        gfac = self._gain_factor()

        return arr*gfac if gfac != 1 else arr


    def image(self, evt, nda=None, **kwa) -> Array2d:
        """
        Create 2-d image.

        Parameters
        ----------
        evt: event
            psana event object, ex. run.events().next().

        mapmode: int, optional, default: 2
            control on overlapping pixels on image map.
            0/1/2/3/4: statistics of entries / last / max / mean pixel intensity / interpolated (TBD) - ascending data index.

        fillholes: bool, optional, default: True
            control on map bins inside the panel with 0 entries from data.
            True/False: fill empty bin with minimal intensity of four neares neighbors/ do not fill.

        vbase: float, optional, default: 0
            value substituted for all image map bins without entry from data.

        Returns
        -------
        image: np.array, ndim=2
        """
        logger.debug('in AreaDretector.image')

        pix_rc = self._cached_pix_rc()
        cco = self._calibc_

        if any(v is None for v in pix_rc):
            self._cached_pixel_coord_indexes(evt, **kwa)
            pix_rc = cco.pix_rc()
            if any(v is None for v in pix_rc): return None

        vbase     = kwa.get('vbase',0)
        mapmode   = kwa.get('mapmode',2)
        fillholes = kwa.get('fillholes',True)

        if mapmode==0: return self.img_entries

        data = self.calib(evt) if nda is None else nda

        if is_none(data, 'AreaDetector.image calib returns None'): return None

        logger.debug(info_ndarr(data, 'data ', last=3))
        rows, cols = pix_rc
        logger.debug(info_ndarr(rows, 'rows ', last=3))
        logger.debug(info_ndarr(cols, 'cols ', last=3))

        img = img_from_pixel_arrays(rows, cols, weight=data, vbase=vbase) # mapmode==1
        if   mapmode==2: img_multipixel_max(img, data, cco.dmulti_pix_to_img_idx)
        elif mapmode==3: img_multipixel_mean(img, data, cco.dmulti_pix_to_img_idx, cco.dmulti_imgidx_numentries)

        if mapmode<4 and fillholes: fill_holes(img, cco.hole_rows, cco.hole_cols)

        return img if mapmode<4 else\
               img_interpolated(data, self._cached_interpol_pars()) if mapmode==4 else\
               self.img_entries


    def _mask_default(self, dtype=DTYPE_MASK):
        o = self._maskalgos()
        return None if o is None else\
               o.mask_default(dtype=dtype)


    def _mask_calib_or_default(self, dtype=DTYPE_MASK):
        o = self._maskalgos()
        return None if o is None else\
               o.mask_calib_or_default(dtype=dtype)


    def _mask_from_status(self, status_bits=0xffff, gain_range_inds=None, dtype=DTYPE_MASK, **kwa):
        logger.info('in areadetector._mask_from_status ==== should be re-implemented for multi-gain detectors')
        o = self._maskalgos()
        return None if o is None else\
               o.mask_from_status(status_bits=status_bits, gain_range_inds=gain_range_inds, dtype=dtype, **kwa)


    def _mask_neighbors(self, mask, rad=9, ptrn='r', **kwa):
        o = self._maskalgos()
        return None if o is None else\
               o.mask_neighbors(mask, rad=rad, ptrn=ptrn, **kwa)


    def _mask_edges(self, width=0, edge_rows=1, edge_cols=1, dtype=DTYPE_MASK, **kwa):
        o = self._maskalgos()
        return None if o is None else\
               o.mask_edges(width=width, edge_rows=edge_rows, edge_cols=edge_cols, dtype=dtype, **kwa)


    def _mask_center(self, wcenter=0, center_rows=1, center_cols=1, dtype=DTYPE_MASK, **kwa):
        o = self._maskalgos()
        return None if o is None else\
               o.mask_center(wcenter=wcenter, center_rows=center_rows, center_cols=center_cols, dtype=dtype, **kwa)


    def _mask_comb(self, status=True, neighbors=False, edges=False, center=False, calib=False, umask=None, dtype=DTYPE_MASK, **kwa):
        """Returns combined mask controlled by the keyword arguments.
           Parameters
           ----------
           - status   : bool : True  - mask from pixel_status constants,
                                       kwa: status_bits=0xffff - status bits to use in mask.
                                       Status bits show why pixel is considered as bad.
                                       Content of the bitword depends on detector and code version.
                                       It is wise to exclude pixels with any bad status by setting status_bits=0xffff.
                                       kwa: gain_range_inds=(0,1,2,3,4) - list of gain range indexes to merge for epix10ka or jungfrau
           - neighbor : bool : False - mask of neighbors of all bad pixels,
                                       kwa: rad=5 - radial parameter of masked region
                                       kwa: ptrn='r'-rhombus, 'c'-circle, othervise square region around each bad pixel
           - edges    : bool : False - mask edge rows and columns of each panel,
                                       kwa: width=0 or edge_rows=1, edge_cols=1 - number of masked edge rows, columns
           - center   : bool : False - mask center rows and columns of each panel consisting of ASICS (cspad, epix, jungfrau),
                                       kwa: wcenter=0 or center_rows=1, center_cols=1 -
                                       number of masked center rows and columns in the segment,
                                       works for cspad2x1, epix100, epix10ka, jungfrau panels
           - calib    : bool : False - apply user's defined mask from pixel_mask constants
           - umask  : np.array: None - apply user's defined mask from input parameters (shaped as data)

           Returns
           -------
           np.array: dtype=np.uint8, shape as det.raw - mask array of 1 or 0 or None if all switches are False.
        """
        o = self._maskalgos()
        return None if o is None else\
               o.mask_comb(status=status, neighbors=neighbors, edges=edges, center=center, calib=calib, umask=umask, dtype=dtype, **kwa)


    def _mask(self, status=True, neighbors=False, edges=False, center=False, calib=False, umask=None, force_update=False, dtype=DTYPE_MASK, **kwa):
        """returns cached mask.
        """
        o = self._maskalgos()
        return None if o is None else\
               o.mask(status=status, neighbors=neighbors, edges=edges, center=center, calib=calib, umask=umask, force_update=force_update, dtype=dtype, **kwa)


if __name__ == "__main__":
    import sys
    sys.exit('See example in test_%s if available...' % sys.argv[0].split('/')[-1])

# EOF
