import os
import ase.io
import numpy as np
from ase import Atoms
from scipy.optimize import minimize
from scipy.sparse import load_npz, save_npz

# TODO remove sparse and keep only scipy.sparse
from sparse import COO

DELTA_SHIFT = 1e-6
MAIN_FOLDER = 'displacement'
SECOND_ORDER_FILE = 'second.npy'
THIRD_ORDER_FILE_SPARSE = 'third.npz'
THIRD_ORDER_FILE = 'third.npy'
REPLICATED_ATOMS_FILE = 'replicated_atoms.xyz'
LIST_OF_INDEX_FILE = 'list_of_index.npy'

# Tolerance for symmetry search
SYMPREC_THIRD_ORDER = 1e-5


class FiniteDifference(object):
    
    def __init__(self,
                 atoms,
                 supercell=(1, 1, 1),
                 second_order=None,
                 third_order=None,
                 calculator=None,
                 calculator_inputs=None,
                 is_persistency_enabled=True,
                 delta_shift=DELTA_SHIFT,
                 folder=MAIN_FOLDER,
                 third_order_symmerty_inputs=None):
        self.atoms = atoms
        self.supercell = supercell
        self.n_atoms = self.atoms.get_masses().shape[0]
        self.n_replicas = np.prod(supercell)
        self.calculator = calculator
        self.calculator_inputs = calculator_inputs
        self.is_persistency_enabled = is_persistency_enabled
        self.folder_name = folder
        self.second_order_delta = delta_shift
        self.third_order_delta = delta_shift
        self.third_order_symmerty_inputs = third_order_symmerty_inputs

        self._replicated_atoms = None
        self._list_of_index = None
        self._second_order = None
        self._third_order = None
        if second_order is not None:
            self.second_order = second_order
        if third_order is not None:
            self.third_order = third_order

    @property
    def second_order(self):
        return self._second_order

    @second_order.getter
    def second_order(self):
        if self._second_order is None:
            if self.is_persistency_enabled:
                try:
                    folder = self.folder_name
                    folder += '/'
                    self._second_order = np.load(folder + SECOND_ORDER_FILE)
                except FileNotFoundError as e:
                    print(e)
            if self._second_order is None:
                self.second_order = self.calculate_second()
        return self._second_order

    @second_order.setter
    def second_order(self, new_second_order):
        if self.is_persistency_enabled:
            folder = self.folder_name
            folder += '/'
            if not os.path.exists(folder):
                os.makedirs(folder)
            np.save(folder + SECOND_ORDER_FILE, new_second_order)
        self._second_order = new_second_order

    @property
    def third_order(self):
        return self._third_order

    @third_order.getter
    def third_order(self):
        if self._third_order is None:
            if self.is_persistency_enabled:
                try:
                    folder = self.folder_name
                    folder += '/'
                    self._third_order = COO.from_scipy_sparse(load_npz(folder + THIRD_ORDER_FILE_SPARSE)) \
                        .reshape((1 * self.n_atoms * 3, self.n_replicas * self.n_atoms * 3, self.n_replicas *
                                  self.n_atoms * 3))
                except FileNotFoundError as e:
                    print(e)
                    try:
                        # TODO: remove this non sparse migration
                        self._third_order = np.load(folder + THIRD_ORDER_FILE)

                        # here we force the migration to the sparse version
                        self.third_order = self._third_order
                    except FileNotFoundError as e:
                        print(e)
            if self._third_order is None:
                self.third_order = self.calculate_third()
        return self._third_order

    @third_order.setter
    def third_order(self, new_third_order):
        if type(new_third_order) == np.ndarray:
            self._third_order = COO.from_numpy(new_third_order)
        else:
            self._third_order = new_third_order
        if self.is_persistency_enabled:
            folder = self.folder_name
            folder += '/'
            if not os.path.exists(folder):
                os.makedirs(folder)
            save_npz(folder + THIRD_ORDER_FILE_SPARSE, self._third_order.reshape((self.n_atoms * 3 * self.n_replicas * \
                                                                                  self.n_atoms * 3,
                                                                                  self.n_replicas * self.n_atoms * 3)).to_scipy_sparse())

    @property
    def replicated_atoms(self):
        return self._replicated_atoms

    @replicated_atoms.getter
    def replicated_atoms(self):
        if self._replicated_atoms is None:
            if self.is_persistency_enabled:
                try:
                    folder = self.folder_name
                    folder += '/'
                    self._replicated_atoms = ase.io.read(folder + REPLICATED_ATOMS_FILE, format='extxyz')
                except FileNotFoundError as e:
                    print(e)
            if self._replicated_atoms is None:
                self.replicated_atoms = self.gen_supercell()
        return self._replicated_atoms

    @replicated_atoms.setter
    def replicated_atoms(self, new_replicated_atoms):
        if self.is_persistency_enabled:
            folder = self.folder_name
            folder += '/'
            if not os.path.exists(folder):
                os.makedirs(folder)
            ase.io.write(folder + REPLICATED_ATOMS_FILE, new_replicated_atoms, format='extxyz')
        self._replicated_atoms = new_replicated_atoms

    @property
    def list_of_index(self):
        return self._list_of_index

    @list_of_index.getter
    def list_of_index(self):
        if self._list_of_index is None:
            if self.is_persistency_enabled:
                try:
                    folder = self.folder_name
                    folder += '/'
                    self._list_of_index = np.load(folder + LIST_OF_INDEX_FILE)
                except FileNotFoundError as e:
                    print(e)
            if self._list_of_index is None:
                n_replicas = np.prod(self.supercell)
                atoms = self.atoms
                n_unit_atoms = self.atoms.positions.shape[0]
                list_of_replicas = (
                        self.replicated_atoms.positions.reshape((n_replicas, n_unit_atoms, 3)) - atoms.positions[
                                                                                                 np.newaxis, :, :])
                self.list_of_index = list_of_replicas[:, 0, :]
        return self._list_of_index

    @list_of_index.setter
    def list_of_index(self, new_list_of_index):
        if self.is_persistency_enabled:
            folder = self.folder_name
            folder += '/'
            if not os.path.exists(folder):
                os.makedirs(folder)
            np.save(folder + LIST_OF_INDEX_FILE, new_list_of_index)
        self._list_of_index = new_list_of_index

    def __convert_to_poscar(self, atoms, supercell=None):
        list_of_types = []
        for symbol in atoms.get_chemical_symbols():
            for i in range(np.unique(atoms.get_chemical_symbols()).shape[0]):
                if np.unique(atoms.get_chemical_symbols())[i] == symbol:
                    list_of_types.append(str(i))

        poscar = {'lattvec': atoms.cell / 10,
                  'positions': (atoms.positions.dot(np.linalg.inv(atoms.cell))).T,
                  'elements': atoms.get_chemical_symbols(),
                  'types': list_of_types}
        if supercell is not None:
            poscar['na'] = supercell[0]
            poscar['nb'] = supercell[1]
            poscar['nc'] = supercell[2]
        return poscar

    def __apply_boundary_with_cell(self, cell, cellinv, dxij):
        # exploit periodicity to calculate the shortest distance, which may not be the one we have
        sxij = dxij.dot(cellinv)
        sxij = sxij - np.round(sxij)
        dxij = sxij.dot(cell)
        return dxij

    def __apply_boundary(self, atoms, dxij):
        # TODO: remove this method
        cell = atoms.cell
        cellinv = np.linalg.inv(cell)
        dxij = self.__apply_boundary_with_cell(atoms.cell, cellinv, dxij)
        return dxij

    def gen_supercell(self):
        supercell = self.supercell
        n_replicas = np.prod(self.supercell)
        n_atoms = self.atoms.positions.shape[0]
        na, nb, nc = self.supercell
        cell = self.atoms.cell
        atoms = self.atoms
        positions = (atoms.positions.dot(np.linalg.inv(atoms.cell)))
        replicated_positions = np.zeros((n_atoms * n_replicas, 3))
        replicated_symbols = []
        for pos in range(n_atoms * n_replicas):
            k, j, i, iat = np.unravel_index(pos, [na, nb, nc, n_atoms])
            replicated_positions[pos, :] = (positions[iat, :] + [i, j, k]) / [na, nb, nc]
            replicated_symbols.append(atoms.symbols[iat])

        replicated_cell = cell * self.supercell
        replicated_cell_inv = np.linalg.inv(replicated_cell)
        self.__apply_boundary_with_cell(replicated_cell, replicated_cell_inv, replicated_positions)
        new_positions = replicated_positions.dot(replicated_cell)
        new_positions = (self.__apply_boundary_with_cell(replicated_cell, replicated_cell_inv, new_positions))
        replicated_atoms = Atoms(positions=new_positions,
                                 symbols=replicated_symbols, cell=replicated_cell, pbc=[1, 1, 1])
        return replicated_atoms

    def optimize(self, method, tol=None):
        if not ((method == 'none') or not method):
            print('Initial max force: ' + "{0:.4e}".format(self.max_force(self.atoms.positions, self.atoms)))
            print('Optimization method ' + method)
            result = minimize(self.max_force, self.atoms.positions, args=self.atoms, jac=self.gradient, method=method,
                              tol=tol)
            print(result.message)
            self.atoms.positions = result.x.reshape((int(result.x.size / 3), 3))
            ase.io.write('minimized_' + str(self) + '.xyz', self.atoms, format='extxyz')
            print('Final max force: ' + "{0:.4e}".format(self.max_force(self.atoms.positions, self.atoms)))
            return self.max_force(self.atoms.positions, self.atoms)

    def max_force(self, x, atoms):
        grad = self.gradient(x, atoms)
        return np.linalg.norm(grad, 2)

    def gradient(self, x, input_atoms):
        atoms = input_atoms.copy()
        atoms.positions = np.reshape(x, (int(x.size / 3.), 3))
        calc = self.calculator(**self.calculator_inputs)
        atoms.set_calculator(calc)
        gr = -1. * atoms.get_forces()
        grad = np.reshape(gr, gr.size)
        return grad

    def calculate_second(self):
        atoms = self.atoms
        print('Calculating second order potential derivatives')
        n_in_unit_cell = len(atoms.numbers)
        replicated_atoms = self.replicated_atoms
        n_atoms = len(replicated_atoms.numbers)
        dx = self.second_order_delta
        second = np.zeros((n_atoms * 3, n_atoms * 3))
        for alpha in range(3):
            for i in range(n_atoms):
                print('Moving atom ' + str(i) + ', direction ' + str(alpha))
                for move in (-1, 1):
                    shift = np.zeros((n_atoms, 3))
                    shift[i, alpha] += move * dx
                    second[i * 3 + alpha, :] += move * self.gradient(replicated_atoms.positions + shift,
                                                                     replicated_atoms)
        n_supercell = int(replicated_atoms.positions.shape[0] / n_in_unit_cell)
        second = second.reshape((n_supercell, n_in_unit_cell, 3, n_supercell, n_in_unit_cell, 3))
        second = second / (2. * dx)
        return second

    def calculate_third(self):
        atoms = self.atoms
        replicated_atoms = self.replicated_atoms

        # TODO: Here we should create it sparse
        n_in_unit_cell = len(atoms.numbers)
        replicated_atoms = replicated_atoms
        n_replicated_atoms = len(replicated_atoms.numbers)
        n_supercell = int(replicated_atoms.positions.shape[0] / n_in_unit_cell)
        dx = self.third_order_delta
        print('Calculating third order potential derivatives')

        if self.third_order_symmerty_inputs is not None:
            from thirdorder_core import SymmetryOperations, Wedge, reconstruct_ifcs
            from thirdorder_espresso import calc_frange, calc_dists
            if self.third_order_symmerty_inputs['SYMPREC']:
                symprec = self.third_order_symmerty_inputs['SYMPREC']
            else:
                symprec = SYMPREC_THIRD_ORDER

            if self.third_order_symmerty_inputs['NNEIGH']:
                nneigh = self.third_order_symmerty_inputs['NNEIGH']
            else:
                # default on full calculation
                self.third_order_symmerty_inputs = None

        if self.third_order_symmerty_inputs is not None:
            poscar = self.__convert_to_poscar(self.atoms)
            f_range = None
            print("Analyzing symmetries")
            symops = SymmetryOperations(
                poscar["lattvec"], poscar["types"], poscar["positions"].T, symprec)
            print("- Symmetry group {0} detected".format(symops.symbol))
            print("- {0} symmetry operations".format(symops.translations.shape[0]))
            print("Creating the supercell")
            sposcar = self.__convert_to_poscar(self.replicated_atoms, self.supercell)
            print("Computing all distances in the supercell")
            dmin, nequi, shifts = calc_dists(sposcar)
            if nneigh != None:
                frange = calc_frange(poscar, sposcar, nneigh, dmin)
                print("- Automatic cutoff: {0} nm".format(frange))
            else:
                frange = f_range
                print("- User-defined cutoff: {0} nm".format(frange))
            print("Looking for an irreducible set of third-order IFCs")
            wedge = Wedge(poscar, sposcar, symops, dmin, nequi, shifts,
                          frange)
            self.wedge = wedge
            print("- {0} triplet equivalence classes found".format(wedge.nlist))
            list4 = wedge.build_list4()
            print('object created')
            nirred = len(list4)
            phipart = np.zeros((3, nirred, n_replicated_atoms))
            for i, e in enumerate(list4):
                jat, iat, jcoord, icoord = e
                print(
                    'Moving atoms ' + str(iat) + ',' + str(jat) + ', direction ' + str(icoord) + ',' + str(jcoord))
                for n in range(4):
                    shift = np.zeros((n_replicated_atoms, 3))
                    isign = (-1) ** (n // 2)
                    jsign = -(-1) ** (n % 2)
                    delta = np.zeros(3)
                    delta[icoord] = isign * dx
                    shift[iat, :] += delta
                    delta = np.zeros(3)
                    delta[jcoord] = jsign * dx
                    shift[jat, :] += delta
                    phipart[:, i, :] += isign * jsign * (
                            -1 * self.gradient(replicated_atoms.positions + shift, replicated_atoms)
                            .reshape(replicated_atoms.positions.shape).T)
            phifull = np.array(reconstruct_ifcs(phipart, self.wedge, list4,
                                                poscar, sposcar))
            phifull = phifull.swapaxes(3, 2).swapaxes(1, 2).swapaxes(0, 1)
            phifull = phifull.swapaxes(4, 3).swapaxes(3, 2)
            phifull = phifull.swapaxes(5, 4)
        else:
            phifull = np.zeros((n_in_unit_cell, 3, n_supercell * n_in_unit_cell, 3, n_supercell * n_in_unit_cell * 3))
            for iat in range(n_in_unit_cell):
                for icoord in range(3):
                    for jat in range(n_supercell * n_in_unit_cell):
                        for jcoord in range(3):
                            print(
                                'Moving atoms ' + str(iat) + ',' + str(jat) + ', direction ' + str(icoord) + ',' + str(
                                    jcoord))
                            for n in range(4):
                                shift = np.zeros((n_replicated_atoms, 3))
                                # TODO: change this silly way to do isign and jsign
                                isign = (-1) ** (n // 2)
                                jsign = -(-1) ** (n % 2)
                                delta = np.zeros(3)
                                delta[icoord] = isign * dx
                                shift[iat, :] += delta
                                delta = np.zeros(3)
                                delta[jcoord] = jsign * dx
                                shift[jat, :] += delta
                                phifull[iat, icoord, jat, jcoord, :] += isign * jsign * (
                                        -1. * self.gradient(replicated_atoms.positions + shift, replicated_atoms))
        phifull = phifull.reshape(
            (1, n_in_unit_cell, 3, n_supercell, n_in_unit_cell, 3, n_supercell, n_in_unit_cell, 3))
        phifull /= (4. * dx * dx)
        return COO.from_numpy(phifull.reshape((self.n_atoms * 3, self.n_replicas * self.n_atoms * 3, self.n_replicas *
                                               self.n_atoms * 3)))