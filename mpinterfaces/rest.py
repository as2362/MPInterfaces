from __future__ import division, unicode_literals

"""
This is essentially just a clone of the MPRester object in pymatgen with
slight modifications to work with MaterialsWeb.

This module provides classes to interface with the MaterialsWeb REST
API v2 to enable the creation of data structures and pymatgen objects using
MaterialsWeb data.
"""

import json
import warnings

from monty.json import MontyDecoder
from pymatgen.core.structure import Structure

__author__ = "Michael Ashton"
__copyright__ = "Copyright 2017, Henniggroup"
__maintainer__ = "Joshua J. Gabriel"
__email__ = "joshgabriel92@gmail.com"
__status__ = "Production"
__date__ = "March 3, 2017"


class MWRester(object):
    """
    A class to conveniently interface with the MaterialsWeb REST
    interface. The recommended way to use MWRester is with the "with" context
    manager to ensure that sessions are properly closed after usage::
        with MWRester("API_KEY") as m:
            do_something
    MWRester uses the "requests" package, which provides for HTTP connection
    pooling. All connections are made via https for security.

    Args:
        api_key (str): A String API key for accessing the MaterialsWeb
            REST interface. Please obtain your API key at
            https://www.materialsweb.org.
        endpoint (str): Url of endpoint to access the MaterialsWeb REST
            interface. Defaults to the standard MaterialsWeb REST
            address, but can be changed to other urls implementing a similar
            interface.
    """

    supported_properties = ("energy", "energy_per_atom", "volume",
                            "formation_energy_per_atom", "nsites",
                            "unit_cell_formula", "pretty_formula",
                            "is_hubbard", "elements", "nelements",
                            "e_above_hull", "hubbards", "is_compatible",
                            "spacegroup", "task_ids", "band_gap", "density",
                            "icsd_id", "icsd_ids", "cif", "total_magnetization",
                            "material_id", "oxide_type", "tags", "elasticity")

    supported_task_properties = ("energy", "energy_per_atom", "volume",
                                 "formation_energy_per_atom", "nsites",
                                 "unit_cell_formula", "pretty_formula",
                                 "is_hubbard",
                                 "elements", "nelements", "e_above_hull",
                                 "hubbards",
                                 "is_compatible", "spacegroup",
                                 "band_gap", "density", "icsd_id", "cif")

    def __init__(self, api_key=None,
                 endpoint="https://www.materialsweb.org/rest"):
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = ""
        self.preamble = endpoint
        import requests
        self.session = requests.Session()
        self.session.headers = {"x-api-key": self.api_key}

    def __enter__(self):
        """
        Support for "with" context.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Support for "with" context.
        """
        self.session.close()

    def _make_request(self, sub_url, payload=None, method="GET",
                      mp_decode=True):
        response = None
        url = self.preamble + sub_url
        try:
            if method == "POST":
                response = self.session.post(url, data=payload, verify=True)
            else:
                # For now, the SSL certificate is being annoying and
                # won't verify. Once it does, we can change this back
                # to verify=True.
                response = self.session.get(url, params=payload, verify=False)
            if response.status_code in [200, 400]:
                if mp_decode:
                    data = json.loads(response.text, cls=MontyDecoder)
                else:
                    data = json.loads(response.text)
                if data["valid_response"]:
                    if data.get("warning"):
                        warnings.warn(data["warning"])
                    return data["response"]
                else:
                    raise MWRestError(data["error"])

            raise MWRestError("REST query returned with error status code {}"
                              .format(response.status_code))

        except Exception as ex:
            msg = "{}. Content: {}".format(str(ex), response.content)\
                if hasattr(response, "content") else str(ex)
            raise MWRestError(msg)

    def get_data(self, chemsys_formula_id, data_type="vasp", prop=""):
        """
        Flexible method to get any data using the MaterialsWeb REST
        interface. Generally used by other methods for more specific queries.
        Format of REST return is *always* a list of dict (regardless of the
        number of pieces of data returned. The general format is as follows:
        [{"material_id": material_id, "property_name" : value}, ...]
        Args:
            chemsys_formula_id (str): A chemical system (e.g., Li-Fe-O),
                or formula (e.g., Fe2O3) or materials_id (e.g., mp-1234).
            data_type (str): Type of data to return. Currently can either be
                "vasp" or "exp".
            prop (str): Property to be obtained. Should be one of the
                MWRester.supported_task_properties. Leave as empty string for a
                general list of useful properties.
        """
        sub_url = "/materials/%s/%s" % (chemsys_formula_id, data_type)
        if prop:
            sub_url += "/" + prop
        return self._make_request(sub_url)

    def get_structure_by_material_id(self, material_id, final=True):
        """
        Get a Structure corresponding to a material_id.
        Args:
            material_id (str): MaterialsWeb material_id (a string,
                e.g., mp-1234).
            final (bool): Whether to get the final structure, or the initial
                (pre-relaxation) structure. Defaults to True.
        Returns:
            Structure object.
        """
        prop = "final_structure" if final else "initial_structure"
        data = self.get_data(material_id)
        return Structure.from_str(data[0][prop], fmt="json")


class MWRestError(Exception):
    """
    Exception class for MWRestAdaptor.
    Raised when the query has problems, e.g., bad query format.
    """
    pass
