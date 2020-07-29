#!/bin/python3

###############################################################################
# Copyright 2020 UChicago Argonne, LLC.
# (c.f. AUTHORS, LICENSE)
# SPDX-License-Identifier: BSD-3-Clause
##############################################################################

import argparse
import re
from starbind import MPI, OpenMP, Ptrace
from tmap.topology import Topology
from tmap.permutation import Permutation

parser = argparse.ArgumentParser()    
parser.add_argument('-m', '--method',
                    choices = ['MPI', 'OpenMP', 'ptrace', 'auto'],
                    default = 'auto',
                    help='''
MPI: starbind is used inside a mpi command line to
bind the local process. Starbind will look for
'MPI_LOCALRANKID', 'OMPI_COMM_WORLD_LOCAL_RANK' in
environment too define the index to pick a resource
in resource list. Only MPI processes will be bound.
------------------------------------------------------
OpenMP: starbind is used to launch an OpenMP
application and bind its threads. Envrionment variable
OMP_PLACES of child application will be set reflecting
the resource list.
------------------------------------------------------
ptrace: starbind is used to launch an application and
bind child threads and processes. ptrace uses ptrace()
system call to catch vfork(), fork(), clone() syscalls
and bind child processes to the next resource in
resource list.
------------------------------------------------------
auto: starbind has to figure out one of above methods.
MPI is tried first. If target environment variables
are not set, then OpenMP is tried. OpenMP will look
into executable linked dynamic libraries with ldd and
try to match a name with openmp, omp. If no match is
found, ptrace is used.''')

parser.add_argument('-t', '--type', help="Topology object type used to bind threads", default='Core', type=str)
parser.add_argument('-p', '--permutation', help="A permutation id to reorder topology objects.", default=0, type=int)
parser.add_argument('-c', '--command', help="The command line to run", required=True, type=str)
parser.add_argument('-v', '--verbose', help="Print resource permutattion", default=False, action='store_true')

args = parser.parse_args()

#Get the list of topology resources
topology = Topology(structure=False)
resources = [ n for n in topology if args.type.lower() in n.type.lower() ]
if len(resources) == 0:
    raise ValueError('Invalid topology type {}. Valid types are: {}'.format(args.type, set(n.type for n in topology)))

# Apply permutation on resources
permutation = Permutation(len(resources), args.permutation)
resources = [ resources[i] for i in permutation.elements ]

# Assign bind method
if args.method == 'MPI':
    binder = MPI(resources)
elif args.method == 'OpenMP':
    binder = OpenMP(resources)
elif args.method == 'ptrace':
    binder = Ptrace(resources)
elif MPI.is_MPI_process():
    binder = MPI(resources)
elif OpenMP.is_OpenMP_application(args.command.split()[0]):
    binder = OpenMP(resources)
else:
    binder = Ptrace(resources)

# Print info
if args.verbose:
    if MPI.is_MPI_process():
        if MPI.get_rank() == 0:
            print('Bind to: {!s}'.format(resources))
            print('Bind with {}'.format(binder.__class__.__name__))
    else:
        print('Bind to: {!s}'.format(resources))
        print('Bind with {}'.format(binder.__class__.__name__))

# Run command
binder.run(args.command)
