#!/bin/python3

###############################################################################
# Copyright 2020 UChicago Argonne, LLC.
# (c.f. AUTHORS, LICENSE)
# SPDX-License-Identifier: BSD-3-Clause
##############################################################################

import argparse
import re
from starbind import MPI, OpenMPI, MPICH, OpenMP, Ptrace
from tmap.topology import Topology
from tmap.permutation import Permutation

parser = argparse.ArgumentParser()    
parser.add_argument('-m', '--method',
                    choices = ['OpenMPI', 'MPICH', 'OpenMP', 'ptrace', 'auto'],
                    default = 'auto',
                    help='''
OpenMPI, MPICH: starbind is used inside a mpi command
line to bind the local process. Depending on weather
it is MPICH or OpenMPI, binding is made via the
command line or via the interception of subprocesses
and their environment variables 'MPI_LOCALRANKID',
'OMPI_COMM_WORLD_LOCAL_RANK'.
Only MPI processes will be bound. Starbind can be used
inside MPI command line or outside and it will use
mpirun.
------------------------------------------------------
OpenMP: starbind is used to launch an OpenMP
application and bind its threads. Envrionment variable
OMP_PLACES of child application will be set reflecting
the resource list. If more threads than locations are
used, then threads are continuously packed on
locations processing units from first location to the
last one.
------------------------------------------------------
ptrace: starbind is used to launch an application and
bind child threads and processes. ptrace uses ptrace()
system call to catch vfork(), fork(), clone() syscalls
and bind child processes to the next resource in
resource list. Bindings are applied in a round-robin
order of resources and will cycle if more processes
than available resources need to be bound.
------------------------------------------------------
auto: starbind has to figure out one of above methods.
MPI is tried first. If target environment variables
are not set and no MPI library was found in the binary
, then OpenMP is tried. OpenMP will look into
executable linked dynamic libraries with ldd and will
try to match a name with openmp, omp. If no match is
found, ptrace is used.''')

parser.add_argument('-t', '--type',
                    help="Topology object type used to bind threads",
                    default='Core', type=str)
parser.add_argument('-p', '--permutation',
                    help="A permutation id to reorder topology objects.",
                    default=0, type=int)
parser.add_argument('-c', '--command',
                    help="The command line to run",
                    required=True, type=str)
parser.add_argument('-n', '--num',
                    help="The number of threads (OpenMP) or processes (MPI) to set.",
                    default=None, type=int)
parser.add_argument('-v', '--verbose',
                    help="Print resource permutattion",
                    default=False, action='store_true')
args = parser.parse_args()

# Get the list of topology resources
topology = Topology(structure=False)
resources = [ n for n in topology if args.type.lower() in n.type.lower() ]
if len(resources) == 0:
    raise ValueError('Invalid topology type {}. Valid types are: {}'\
                     .format(args.type, set(n.type for n in topology)))

# Apply permutation on resources
permutation = Permutation(len(resources), args.permutation)
resources = [ resources[i] for i in permutation.elements ]

bin=args.command.split()[0]

# Assign bind method
if args.method == 'OpenMPI':
    binder = OpenMPI(resources, num_procs=args.num)
if args.method == 'MPICH':
    binder = MPICH(resources, num_procs=args.num)
elif args.method == 'OpenMP':
    binder = OpenMP(resources, num_threads=args.num)
elif args.method == 'ptrace':
    binder = Ptrace(resources)
elif MPI.is_MPI_process() or MPI.is_MPI_application(bin):
    binder = OpenMPI(resources, num_procs=args.num)
elif OpenMP.is_OpenMP_application(bin):
    binder = OpenMP(resources, num_threads=args.num)
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

#Run command
binder.run(args.command)
