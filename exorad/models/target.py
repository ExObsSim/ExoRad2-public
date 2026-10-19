from __future__ import annotations

from typing import Any

import numpy as np
from astropy import (
    constants as cc,
    units as u,
)

from exorad.log.logger import Logger
from exorad.models.source import CustomSed, DownloadedSed, Star


class Target(Logger):
    """
    Target base class
    """

    # These attributes are attached dynamically by the pipeline tasks (and
    # probed with ``hasattr``), so they are declared here as annotations only:
    # no value is bound, so instances still start without them.
    star: Target
    planet: Target
    name: Any
    id: int
    sed: Any
    model: Any
    table: Any
    luminosity: Any

    def __init__(self) -> None:
        self.set_log_name()

    def calc_logg(self, M: u.Quantity, R: u.Quantity) -> float:
        m = M.si
        r = R.si
        g = cc.G * m / r**2
        g = g.to(u.cm / u.s**2)

        return float(np.log10(g.value))

    def update_target(self, obj: object) -> None:
        if isinstance(obj, (Star, CustomSed, DownloadedSed)):
            self.star.luminosity = obj.luminosity
            self.star.sed = obj.sed
            self.star.model = obj.model
            self.debug("target updated")
        else:
            self.warning(f"Object type {type(obj)} not implemented")

    def write(self, output: Any) -> Any:
        targets_out = output.create_group("targets")
        group_name = str(self.name)
        target_dict = self.to_dict()
        targets_out.store_dictionary(target_dict, group_name=group_name)
        self.info(f"target {self.name} saved")
        return output

    def to_dict(self) -> dict:
        from exorad.utils.util import to_dict

        return to_dict(self)
