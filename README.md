# StarBind

Starbind is a command line tool to bind threads and processes of HPC applications on the local node.
Starbind currently supports: 
* openmp
* pthread
* openmpi
* mpich
* clone(), fork(), vfork() system calls
To bind threads.

## Requirements.

* linux operating system
* python3 or greater
* hwloc, lstopo (hwloc) and hwloc-info.
* tmap (https://github.com/NicolasDenoyelle/tmap)

## Usage

Starbind takes a topology resource type (e.g 'core', 'package') and a permutation
of these resources as input and will bind application child threads / processes
to these resources.

See `starbind --help` for more info on the command line.
See `tmap` pages for more info on permutations. 

## Module

Starbind can also be used as python module.

```
from starbind import OpenMP
from tmap import topology

cores = [ n for n in topology if n.type == 'Core' ]
binding = OpenMP(cores)
output = binding.getoutput('/home/user/application --foo --bar baz')
print(output)
```

## Tests

1. Compile tests:

``` sh
make -C tests
```
Make sure that Makefile uses the good compilers and flags for your machine.

Be carefull to use the same version of hwloc library as your mpi version.
this can be done by adding `-Lpath/to/hwloc` before the flag -lhwloc.

2. Run tests:

``` sh
python3 starbind/cpubind.py
mpiexec -np 4 python3 starbind/cpubind.py
```

