from __future__ import division, unicode_literals, print_function

"""
combines instrument, calibrate and interfaces to perform the calibration
and run the actual jobs
"""

import sys
import shutil
import os
import json
import logging

import numpy as np

from pymatgen import Lattice
from pymatgen.core.structure import Structure
from pymatgen.io.vaspio.vasp_input import Incar, Poscar, Potcar, Kpoints

from mpinterfaces.calibrate import Calibrate, CalibrateMolecule
from mpinterfaces.calibrate import CalibrateSlab, CalibrateBulk
from mpinterfaces.calibrate import CalibrateInterface      
from mpinterfaces.interface import Interface

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
sh = logging.StreamHandler(stream=sys.stdout)
sh.setFormatter(formatter)
logger.addHandler(sh)


class Measurement(object):
    """
    Takes in calibrate objects and use that to perform various 
    measurement calcuations such as solvation, ligand binding energy etc
    
    default behaviour: sets up and runs static calculations for all
    the given calibrate jobs

    Override this classfor custom measuremnts
    """
    def __init__(self, cal_objs, setup_dir='.', parent_job_dir='.',
                 job_dir='./Measurement'):
        self.encut = None
        self.kpoints = None
        self.vac_spacing = None
        self.slab_thickness = None
        self.jobs = []
        self.handlers = []
        self.calmol = []
        self.calslab = []
        self.calbulk = []
        self.cal_objs = cal_objs
        self.job_dir = job_dir
        for obj in cal_objs:
            obj.old_jobs = obj.jobs
            obj.jobs = []
            obj.old_job_dir_list = cal.job_dir_list
            obj.job_dir_list = []

    def setup(self):
        """
        setup static jobs for all the calibrate objects
        copies CONTCAR to POSCAR
        sets NSW = 0
        """
        for cal in self.cal_objs:
            cal.incar['NSW'] = 0
            for i, jdir in enumerate(cal.old_job_dir_list):
                job_dir = self.job_dir+os.sep+ \
                  cal.old_jobs[i].name.replace(os.sep, '_').replace('.', '_')+ \
                  os.sep+'STATIC'
                logger.info('setting up job in {}'.format(job_dir))                  
                contcar_file = jdir+os.sep+'CONTCAR'
                logger.info('setting poscar file from {}'.format(contcar_file))
                cal.poscar = Poscar.from_file(contcar_file)
                cal.add_job(job_dir=job_dir)

    def run(self, job_cmd=None):
        """ run jobs """
        for cal in self.cal_objs:
            cal.run()

    def get_energy(self, cal):
        """
        measures the energy of a single cal object
        a single cal object can have multiple calculations
        returns energies lists
        """
        energies = []
        for job_dir in cal.job_dir_list:
            drone = MPINTVaspDrone(inc_structure=True, 
                                   inc_incar_n_kpoints=False)
            bg =  BorgQueen(drone)
            #bg.parallel_assimilate(rootpath)        
            bg.serial_assimilate(job_dir)
            allentries =  bg.get_data()
            for e in allentries:
                if e:
                    energies.append(e.energy)
                    logger.debug('energy from directory {0} : {1}'
                                 .format(job_dir,e.energy))
        return energies

    def make_measurements(self):
        """
        gets the energies and processes it
        override this for custom measurements
        """
        energies = []
        for cal in self.cal_objs:
            energies.append(self.get_energy(cal))


class MeasurementSolvation(Measurement):
    """
    Solvation
    """
    def __init__(self, cal_objs, setup_dir='.', parent_job_dir='.', job_dir='./MeasurementSolvation',
                 sol_params={'EB_K':80, 'TAU':0}):
        Measurement.__init__(self, cal_objs=cal_objs, setup_dir=setup_dir, 
                            parent_job_dir=parent_job_dir, job_dir=job_dir)
        self.sol_params = sol_params


    def setup(self):
        """
        setup solvation jobs for the calibrate objects
        copies WAVECAR and sets the solvation params in the incar file
        also dumps system.json file in each directory for database
        crawler
        
        mind: works only for cal objects that does only single calculations
        """
        for cal in self.cal_objs:
            cal.incar['LSOL'] = '.TRUE.'            
            job_dir = self.job_dir+os.sep+ \
                    cal.old_jobs[0].name.replace(os.sep, '_').replace('.', '_')+ \
                    os.sep + 'SOL'       
            for k, v in self.sol_params:
                cal.incar[k] = v
            if not os.path.exists(job_dir):            
                os.makedirs(job_dir)
            with open(job_dir+os.sep+'system.json', 'w') as f:
                json.dump(self.sol_params, f)
            wavecar_file = cal.old_job_dir_list[0]+os.sep+'WAVECAR'
            shutil.copy(wavecar_file, job_dir+os.sep+'WAVECAR')
            cal.add_job(job_dir=job_dir)

    def make_measurements(self):
        """
        get solvation energies
        """
        pass


class MeasurementInterface(Measurement):
    """
    Interface
    """
    def __init__(self, cal_objs, setup_dir='.', parent_job_dir='.',
                 job_dir='./MeasurementInterface'):
        Measurement.__init__(self, cal_objs=cal_objs, setup_dir=setup_dir, 
                            parent_job_dir=parent_job_dir, job_dir=job_dir)
        self.cal_slabs = []
        self.cal_interfaces = []
        self.cal_ligands = []
        for cal in self.cal_objs:
            if isinstance(cal, CalibrateSlab):
                self.cal_slabs.append(cal)
            elif isinstance(cal, CalibrateInterface):
                self.cal_interfaces.append(cal)
            elif isinstance(cal, CalibrateMolecule):
                self.cal_ligands.append(cal)
                
    def setup(self):
        """
        setup static jobs for the calibrate objects
        copies CONTCAR to POSCAR
        sets NSW = 0
        write system.json file for database crawler
        """
        d = {}
        for cal in self.cal_objs:
            cal.incar['NSW'] = 0
            for i, jdir in enumerate(cal.old_job_dir_list):
                job_dir = self.job_dir+os.sep+ \
                    cal.old_jobs[i].name.replace(os.sep, '_').replace('.', '_')+ \
                    os.sep+'STATIC'
                contcar_file = jdir+os.sep+'CONTCAR'            
                cal.poscar = Poscar.from_file(contcar_file)
                if cal in self.cal_slabs or cal in self.cal_interfaces:
                    try:
                        d['hkl'] = list(cal.system.miller_index)
                    except:
                        logger.critical('the calibrate object doesnt have a system set for calibrating')
                if cal in self.cal_interfaces:
                    try:
                        d['ligand'] = cal.system.ligand.composition.formula
                    except:
                        logger.critical('the calibrate object doesnt have a system set for calibrating')                        
                if not os.path.exists(job_dir):
                    os.makedirs(job_dir)
                if d:
                    with open(job_dir+os.sep+'system.json', 'w') as f:
                        json.dump(d, f)
                cal.add_job(job_dir=job_dir)

    def make_measurements(self):
        """
        get the slab, ligand and interface energies
        compute binding energies
        """
        E_interfaces = {}
        E_slabs ={}
        E_ligands = {}
        for cal in self.cal_slabs:
            key = str(cal.system.miller_index)
            E_slabs[key] = self.get_energy(cal)
        for cal in self.cal_ligands:
            key = cal.system.ligand.composition.formula
            E_ligands[key] = self.get_energy(cal)
        for cal in self.cal_interfaces:
            key_slab = str(cal.system.miller_index)            
            key_ligand = cal.system.ligand.composition.formula            
            key = key_slab + key_ligand
            E_interfaces[key] = self.get_energy(cal)
            E_binding[key] = E_interfaces[key] \
              - E_slabs[key_slab] \
              - cal.system.n_ligands * E_ligands[key_ligand]
        logger.info('Binding energy = {}'.format(E_binding))

#test
if __name__=='__main__':
    from pymatgen.core.structure import Structure, Molecule
    from mpinterfaces import Ligand
    
    # PbS 100 surface with single hydrazine as ligand
    strt= Structure.from_file("POSCAR_Pt") 
    mol_struct= Structure.from_file("POSCAR_diacetate")
    mol= Molecule(mol_struct.species, mol_struct.cart_coords)
    hydrazine= Ligand([mol])
    supercell = [1,1,1]
    hkl = [1,0,0]
    min_thick = 19
    min_vac = 12
    surface_coverage = 0.01
    adsorb_on_species = 'Pt'
    adatom_on_lig='Pb'
    displacement = 3.0
    iface = Interface(strt, hkl=hkl, min_thick=min_thick, min_vac=min_vac,
                      supercell=supercell, surface_coverage=0.01,
                      ligand=hydrazine, displacement=displacement,
                      adatom_on_lig=adatom_on_lig,
                      adsorb_on_species= adsorb_on_species,
                      primitive= False)
    iface.create_interface()
    #iface.sort()

    incarparams = {'System':'test',
                   'ENCUT': 400,
                   'ISMEAR': 1,
                   'SIGMA': 0.1,
                   'EDIFF':1E-6}
    incar = Incar(params=incarparams)
    poscar = Poscar(iface, comment="system",
                    selective_dynamics=None,
                    true_names=True, velocities=None,
                    predictor_corrector=None)
    potcar = Potcar(symbols=poscar.site_symbols, functional='PBE',
                    sym_potcar_map=None)
    kpoints = Kpoints.monkhorst_automatic(kpts=(16, 16, 16), shift=(0, 0, 0))

    cal = CalibrateInterface(incar, poscar, potcar, kpoints, system=iface,
                        job_dir='test', job_cmd=['ls','-lt'])
    cal.setup()
    cal.run()
    #list of calibrate objects
    cal_objs = [cal]
    #check whether the cal jobs were done 
    #Calibrate.check_calcs(cal_objs)
    #set the measurement
    measure = MeasurementInterface(cal_objs, job_dir='./Measurements')
    measure.setup()
    measure.run()
