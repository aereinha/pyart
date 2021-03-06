"""
pyart.io.rsl
============

Python wrapper around the RSL library.

.. autosummary::
    :toctree: generated/

    read_rsl
    VOLUMENUM2RSLNAME
    RSLNAME2VOLUMENUM

"""

# Nothing from this module is imported into pyart.io if RSL is not installed.
import numpy as np

from ..config import FileMetadata, get_fillvalue
from . import _rsl_interface
from ..core.radar import Radar
from .common import dms_to_d, make_time_unit_str


def read_rsl(filename, field_names=None, additional_metadata=None,
             file_field_names=False, exclude_fields=None,
             radar_format=None, callid=None):
    """
    Read a file supported by RSL

    Parameters
    ----------
    filename : str or RSL_radar
        Name of file whose format is supported by RSL.
    field_names : dict, optional
        Dictionary mapping RSL data type names to radar field names. If a
        data type found in the file does not appear in this dictionary or has
        a value of None it will not be placed in the radar.fields dictionary.
        A value of None, the default, will use the mapping defined in the
        Py-ART configuration file.
    additional_metadata : dict of dicts, optional
        Dictionary of dictionaries to retrieve metadata from during this read.
        This metadata is not used during any successive file reads unless
        explicitly included.  A value of None, the default, will not
        introduct any addition metadata and the file specific or default
        metadata as specified by the Py-ART configuration file will be used.
    file_field_names : bool, optional
        True to use the RSL data type names for the field names. If this
        case the field_names parameter is ignored. The field dictionary will
        likely only have a 'data' key, unless the fields are defined in
        `additional_metadata`.
    exclude_fields : list or None, optional
        List of fields to exclude from the radar object. This is applied
        after the `file_field_names` and `field_names` parameters.
    radar_format : str or None
        Format of the radar file.  Must be 'wsr88d' or None.
    callid : str or None
        Four letter NEXRAD radar Call ID, only used when radar_format is
        'wsr88d'.

    Returns
    -------
    radar : Radar
        Radar object.

    """
    # create metadata retrieval object
    filemetadata = FileMetadata('rsl', field_names, additional_metadata,
                                file_field_names, exclude_fields)

    # read the file, determine common parameters
    fillvalue = get_fillvalue()
    rslfile = _rsl_interface.RslFile(filename, radar_format, callid)
    available_vols = rslfile.available_moments()
    first_volume = rslfile.get_volume(available_vols[0])
    first_sweep = first_volume.get_sweep(0)
    first_ray = first_sweep.get_ray(0)
    nsweeps = first_volume.nsweeps

    # scan_type, sweep_mode, fixed_angle
    sweep_mode = filemetadata('sweep_mode')
    fixed_angle = filemetadata('fixed_angle')

    if first_sweep.azimuth == -999.0:
        scan_type = 'ppi'
        sweep_mode['data'] = np.array(nsweeps * ['azimuth_surveillance'])
        fixed_angle['data'] = first_volume.get_sweep_elevs()
    else:
        scan_type = 'rhi'
        sweep_mode['data'] = np.array(nsweeps * ['rhi'])
        fixed_angle['data'] = first_volume.get_sweep_azimuths()

    # time
    time = filemetadata('time')
    datetimes = []
    for i in range(nsweeps):
        sweep = first_volume.get_sweep(i)
        for j in range(sweep.nrays):
            datetimes.append(sweep.get_ray(j).get_datetime())
    t_start = min(datetimes)
    t_delta = [t-t_start for t in datetimes]
    # microseconds not needed since RSL only stores time to sec precision.
    time['data'] = np.array(
        [td.seconds + td.days*3600*24 for td in t_delta], dtype=np.float64)
    time['units'] = make_time_unit_str(t_start)

    # range
    _range = filemetadata('range')
    gate0 = first_ray.range_bin1
    gate_size = first_ray.gate_size
    ngates = first_ray.nbins
    _range['data'] = gate0 + gate_size * np.arange(ngates, dtype='float32')
    _range['meters_to_center_of_first_gate'] = _range['data'][0]
    _range['meters_between_gates'] = np.array(gate_size, dtype='float32')

    # fields
    # transfer only those which are available
    fields = {}
    for volume_num in available_vols:

        rsl_field_name = VOLUMENUM2RSLNAME[volume_num]
        field_name = filemetadata.get_field_name(rsl_field_name)
        if field_name is None:
            continue

        # extract the field and mask
        data = rslfile.get_volume_array(volume_num)
        data[np.where(np.isnan(data))] = fillvalue
        data[np.where(data == 131072)] = fillvalue
        data = np.ma.masked_equal(data, fillvalue)

        # create the field dictionary
        field_dic = filemetadata(field_name)
        field_dic['data'] = data
        field_dic['_FillValue'] = fillvalue
        fields[field_name] = field_dic

    # metadata
    metadata = filemetadata('metadata')
    metadata['original_container'] = 'rsl'
    rsl_dict = rslfile.get_radar_header()
    need_from_rsl_header = {
        'name': 'instrument_name', 'project': 'project', 'state': 'state',
        'country': 'country'}  # rsl_name : radar_metadata_name
    for rsl_key, metadata_key in need_from_rsl_header.iteritems():
        metadata[metadata_key] = rsl_dict[rsl_key]

    # latitude
    latitude = filemetadata('latitude')
    lat = dms_to_d((rsl_dict['latd'], rsl_dict['latm'], rsl_dict['lats']))
    latitude['data'] = np.array([lat], dtype='float64')

    # longitude
    longitude = filemetadata('longitude')
    lon = dms_to_d((rsl_dict['lond'], rsl_dict['lonm'], rsl_dict['lons']))
    longitude['data'] = np.array([lon], dtype='float64')

    # altitude
    altitude = filemetadata('altitude')
    altitude['data'] = np.array([rsl_dict['height']], dtype='float64')

    # sweep_number, sweep_mode, sweep_start_ray_index, sweep_end_ray_index
    sweep_number = filemetadata('sweep_number')
    sweep_start_ray_index = filemetadata('sweep_start_ray_index')
    sweep_end_ray_index = filemetadata('sweep_end_ray_index')

    sweep_number['data'] = np.arange(nsweeps, dtype='int32')
    ray_count = first_volume.get_nray_array()   # array of rays in each sweep
    ssri = np.cumsum(np.append([0], ray_count[:-1])).astype('int32')
    sweep_start_ray_index['data'] = ssri
    sweep_end_ray_index['data'] = np.cumsum(ray_count).astype('int32') - 1

    # azimuth, elevation
    azimuth = filemetadata('azimuth')
    elevation = filemetadata('elevation')
    _azimuth, _elevation = first_volume.get_azimuth_and_elev_array()
    azimuth['data'] = _azimuth
    elevation['data'] = _elevation

    # instrument_parameters
    prt = filemetadata('prt')
    prt_mode = filemetadata('prt_mode')
    nyquist_velocity = filemetadata('nyquist_velocity')
    unambiguous_range = filemetadata('unambiguous_range')
    beam_width_h = filemetadata('radar_beam_width_h')
    beam_width_v = filemetadata('radar_beam_width_v')

    pm_data, nv_data, pr_data, ur_data = first_volume.get_instr_params()
    prt['data'] = pr_data
    prt_mode['data'] = pm_data
    nyquist_velocity['data'] = nv_data
    unambiguous_range['data'] = ur_data
    beam_width_h['data'] = np.array([first_sweep.horz_half_bw * 2.],
                                    dtype='float32')
    beam_width_v['data'] = np.array([first_sweep.vert_half_bw * 2.],
                                    dtype='float32')

    instrument_parameters = {'unambiguous_range': unambiguous_range,
                             'prt_mode': prt_mode, 'prt': prt,
                             'nyquist_velocity': nyquist_velocity,
                             'radar_beam_width_h': beam_width_h,
                             'radar_beam_width_v': beam_width_v}

    return Radar(
        time, _range, fields, metadata, scan_type,
        latitude, longitude, altitude,
        sweep_number, sweep_mode, fixed_angle, sweep_start_ray_index,
        sweep_end_ray_index,
        azimuth, elevation,
        instrument_parameters=instrument_parameters)


VOLUMENUM2RSLNAME = {
    0: 'DZ',
    1: 'VR',
    2: 'SW',
    3: 'CZ',
    4: 'ZT',
    5: 'DR',
    6: 'LR',
    7: 'ZD',
    8: 'DM',
    9: 'RH',
    10: 'PH',
    11: 'XZ',
    12: 'CD',
    13: 'MZ',
    14: 'MD',
    15: 'ZE',
    16: 'VE',
    17: 'KD',
    18: 'TI',
    19: 'DX',
    20: 'CH',
    21: 'AH',
    22: 'CV',
    23: 'AV',
    24: 'SQ',
    25: 'VS',
    26: 'VL',
    27: 'VG',
    28: 'VT',
    29: 'NP',
    30: 'HC',
    31: 'VC',
    32: 'V2',
    33: 'S2',
    34: 'V3',
    35: 'S3',
    36: 'CR',
    37: 'CC',
    38: 'PR',
    39: 'SD',
    40: 'ZZ',
    41: 'RD',
    42: 'ET',
    43: 'EZ',
}

RSLNAME2VOLUMENUM = dict([(v, k) for k, v in VOLUMENUM2RSLNAME.iteritems()])
