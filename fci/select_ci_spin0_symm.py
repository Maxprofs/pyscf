#!/usr/bin/env python
#
# Author: Qiming Sun <osirpt.sun@gmail.com>
#

import ctypes
import numpy
from pyscf import lib
from pyscf import ao2mo
from pyscf.fci import direct_spin1
from pyscf.fci import direct_spin1_symm
from pyscf.fci import select_ci
from pyscf.fci import select_ci_symm
from pyscf.fci import select_ci_spin0

libfci = lib.load_library('libfci')

def contract_2e(eri, civec_strs, norb, nelec, link_index=None, orbsym=None):
    ci_coeff, nelec, ci_strs = select_ci._unpack(civec_strs, nelec)
    if link_index is None:
        link_index = select_ci._all_linkstr_index(ci_strs, norb, nelec)
    cd_indexa, dd_indexa, cd_indexb, dd_indexb = link_index
    na, nlinka = nb, nlinkb = cd_indexa.shape[:2]
    ma, mlinka = mb, mlinkb = dd_indexa.shape[:2]

    eri = ao2mo.restore(1, eri, norb)
    eri1 = eri.transpose(0,2,1,3) - eri.transpose(0,2,3,1)
    idx,idy = numpy.tril_indices(norb, -1)
    idx = idx * norb + idy
    eri1 = lib.take_2d(eri1.reshape(norb**2,-1), idx, idx) * 2
    eri1, dd_indexa, dimirrep = select_ci_symm.reorder4irrep_minors(eri1, norb, dd_indexa, orbsym)
    fcivec = ci_coeff.reshape(na,nb)
    ci1 = numpy.zeros_like(fcivec)
    # (aa|aa)
    if nelec[0] > 1:
        libfci.SCIcontract_2e_aaaa_symm(eri1.ctypes.data_as(ctypes.c_void_p),
                                        fcivec.ctypes.data_as(ctypes.c_void_p),
                                        ci1.ctypes.data_as(ctypes.c_void_p),
                                        ctypes.c_int(norb),
                                        ctypes.c_int(na), ctypes.c_int(nb),
                                        ctypes.c_int(ma), ctypes.c_int(mlinka),
                                        dd_indexa.ctypes.data_as(ctypes.c_void_p),
                                        dimirrep.ctypes.data_as(ctypes.c_void_p),
                                        ctypes.c_int(len(dimirrep)))

    h_ps = numpy.einsum('pqqs->ps', eri) * (.5/nelec[0])
    eri1 = eri.copy()
    for k in range(norb):
        eri1[k,k,:,:] += h_ps
        eri1[:,:,k,k] += h_ps
    eri1 = ao2mo.restore(4, eri1, norb)
    eri1, cd_indexa, dimirrep = direct_spin1_symm.reorder4irrep(eri1, norb, cd_indexa, orbsym)
    # (bb|aa)
    libfci.SCIcontract_2e_bbaa_symm(eri1.ctypes.data_as(ctypes.c_void_p),
                                    fcivec.ctypes.data_as(ctypes.c_void_p),
                                    ci1.ctypes.data_as(ctypes.c_void_p),
                                    ctypes.c_int(norb),
                                    ctypes.c_int(na), ctypes.c_int(nb),
                                    ctypes.c_int(nlinka), ctypes.c_int(nlinkb),
                                    cd_indexa.ctypes.data_as(ctypes.c_void_p),
                                    cd_indexa.ctypes.data_as(ctypes.c_void_p),
                                    dimirrep.ctypes.data_as(ctypes.c_void_p),
                                    ctypes.c_int(len(dimirrep)))

    lib.transpose_sum(ci1, inplace=True)
    return select_ci._as_SCIvector(ci1.reshape(ci_coeff.shape), ci_strs)

def kernel(h1e, eri, norb, nelec, ci0=None, level_shift=1e-3, tol=1e-10,
           lindep=1e-14, max_cycle=50, max_space=12, nroots=1,
           davidson_only=False, pspace_size=400, orbsym=None, wfnsym=None,
           select_cutoff=1e-3, ci_coeff_cutoff=1e-3, **kwargs):
    return direct_spin1._kfactory(SelectCI, h1e, eri, norb, nelec, ci0,
                                  level_shift, tol, lindep, max_cycle,
                                  max_space, nroots, davidson_only,
                                  pspace_size, select_cutoff=select_cutoff,
                                  ci_coeff_cutoff=ci_coeff_cutoff, **kwargs)


class SelectCI(select_ci_symm.SelectCI):
    def contract_2e(self, eri, civec_strs, norb, nelec, link_index=None,
                    orbsym=None, **kwargs):
        if orbsym is None:
            orbsym = self.orbsym
        if hasattr(civec_strs, '_strs'):
            self._strs = civec_strs._strs
        else:
            assert(civec_strs.size == len(self._strs[0])*len(self._strs[1]))
            civec_strs = select_ci._as_SCIvector(civec_strs, self._strs)
        return contract_2e(eri, civec_strs, norb, nelec, link_index, orbsym)

    def make_hdiag(self, h1e, eri, ci_strs, norb, nelec):
        return select_ci_spin0.make_hdiag(h1e, eri, ci_strs, norb, nelec)

    enlarge_space = select_ci_spin0.enlarge_space

SCI = SelectCI


if __name__ == '__main__':
    from functools import reduce
    from pyscf import gto
    from pyscf import scf
    from pyscf import ao2mo
    from pyscf import symm

    mol = gto.Mole()
    mol.verbose = 0
    mol.output = None
    mol.atom = [
        ['O', ( 0., 0.    , 0.   )],
        ['H', ( 0., -0.757, 0.587)],
        ['H', ( 0., 0.757 , 0.587)],]
    mol.basis = 'sto-3g'
    mol.symmetry = 1
    mol.build()
    m = scf.RHF(mol).run()

    norb = m.mo_coeff.shape[1]
    nelec = mol.nelectron - 2
    h1e = reduce(numpy.dot, (m.mo_coeff.T, scf.hf.get_hcore(mol), m.mo_coeff))
    eri = ao2mo.incore.full(m._eri, m.mo_coeff)
    orbsym = symm.label_orb_symm(mol, mol.irrep_id, mol.symm_orb, m.mo_coeff)

    myci = SelectCI().set(orbsym=orbsym)
    e1, c1 = myci.kernel(h1e, eri, norb, nelec)
    myci = direct_spin1_symm.FCISolver().set(orbsym=orbsym)
    e2, c2 = myci.kernel(h1e, eri, norb, nelec)
    print(e1 - e2)
