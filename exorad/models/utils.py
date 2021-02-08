
def get_wl_col_name(data, description=None):
    wl_colname = None
    if description is not None and 'wl_col_name' in description:
        wl_colname = description['wl_col_name']['value']
    else:
        for wl_key in ['Wavelength', 'wavelength']:
            if wl_key in data.keys():
                wl_colname= wl_key
    if wl_key is None:
        raise KeyError('Wavelength column not found in transmission data file')
    return wl_colname