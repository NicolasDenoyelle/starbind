# StarBind

Starbind is a command line tool to bind threads and processes of HPC applications on the local node.
Starbind currently supports: 
* openmp
* pthread
* openmpi
* mpich
* clone(), fork(), vfork() system calls

## Requirements.

* linux operating system
* python3 or greater
* hwloc, lstopo (hwloc) and hwloc-info.
* tmap (https://github.com/NicolasDenoyelle/tmap)

## Install

``` sh
python3 setup.py install --user
```

## Usage

Starbind takes a topology resource type (e.g 'core', 'package') and a permutation
of these resources as input and will bind application child threads / processes
to these resources.
See [tmap](https://github.com/NicolasDenoyelle/tmap) pages for more info on permutations.

* Show command line help for more info.
``` sh
python3 -m starbind --help
```

### Examples

* Binding 8 openmp test threads on Cores:
``` sh
python3 -m starbind -v -n 8 -c "./openmp"
Bind to: [Core:0, Core:1, Core:2, Core:3, Core:4, Core:5, Core:6, Core:7]
Bind with OpenMP
0x00000003
0x0000000c
0x00000030
0x000000c0
0x00000300
0x00000c00
0x00003000
0x0000c000
```

* Reversing core order:
``` sh
python3 -m starbind -v -n 8 -c "./openmp" -p -1
Bind to: [Core:7, Core:6, Core:5, Core:4, Core:3, Core:2, Core:1, Core:0]
Bind with OpenMP
0x0000c000
0x00003000
0x00000c00
0x00000300
0x000000c0
0x00000030
0x0000000c
0x00000003
```

* Binding openmp test with openmp runtime on L3 caches 
``` sh
python3 -m starbind -n 4 -t l3 -v -c "./openmp"

Bind to: [L3Cache:0, L3Cache:1]
Bind with OpenMP
0x000000ff
0x000000ff
0x0000ff00
0x0000ff00
```

* Binding openmp test with ptrace on L3 caches 
``` sh
python3 -m starbind -m ptrace -t l3 -v -c "./openmp 4"
Bind to: [L3Cache:0, L3Cache:1]
Bind with Ptrace
0x000000ff
0x0000ff00
0x000000ff
0x0000ff00
```

* Use `mpirun`` and `starbind` to bind processes on node cores. 
``` sh
mpirun -np 4 python3 -m starbind -v -c "./mpi"

Bind to: [Core:0, Core:1, Core:2, Core:3, Core:4, Core:5, Core:6, Core:7]
Bind with MPI
0x00000003
0x0000000c
0x00000030
0x000000c0
```

* Run mpi test on local machine with the same conditions as previous test but
without `mpirun``.
``` sh
python3 -m starbind -n 4 -v -c "./mpi"

Bind to: [Core:0, Core:1, Core:2, Core:3, Core:4, Core:5, Core:6, Core:7]
Bind with MPI
0x00000003
0x0000000c
0x00000030
0x000000c0
```

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
this can be done by adding `-Lpath/to/hwloc` before the flag `-lhwloc`.

2. Run tests:

``` sh
python3 starbind/cpubind.py
mpiexec -np 4 python3 starbind/cpubind.py
```

