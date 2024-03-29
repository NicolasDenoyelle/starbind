###############################################################################
# Copyright 2020 UChicago Argonne, LLC.
# (c.f. AUTHORS, LICENSE)
# SPDX-License-Identifier: BSD-3-Clause
##############################################################################

import os
import sys
import ctypes
import time
import subprocess
import re
from tempfile import mkstemp as tmp
from itertools import cycle
from signal import SIGSTOP, SIGCONT, SIGTRAP, SIGKILL, SIGCHLD
from socket import gethostname
from copy import deepcopy
from datetime import timedelta

def ldd(file):
    """
    Return a list of library names linked with the file.
    """
    regex = re.compile('\t(?P<m>[a-zA-Z0-9/_\-]+)[.]so.*')
    out = subprocess.getoutput("ldd "+file)
    out = out.split('\n')
    out = [ regex.match(o) for o in out ]
    out = [ o.group(1) for o in out if o is not None ]
    return out

def bind_process(resource, pid):
    """
    Function to bind thread on next resource.
    """
    cmd = 'hwloc-bind --cpubind {} --pid {}'.format(resource.cpuset, pid)
    subprocess.getoutput(cmd)

def bind_thread(resource, tid):
    """
    Function to bind thread on next resource.
    """
    cmd = 'hwloc-bind --cpubind {} --tid {}'.format(resource.cpuset, tid)
    subprocess.getoutput(cmd)

class Binding:
    """
    Base class representing a binding method.
    """

    def __init__(self, resource_list):
        """
        Standard initializer.
        @param resource_list: A list of topology objects. See tmap.topology.
        """
        self.resource_list = resource_list

    def __str__(self):
        return str(self.resource_list)

    def run(self, cmd, env=os.environ):
        """
        Subprocess launcher enforcing binding.
        @param cmd: The command line string to launch.
        """
        cmd = cmd.split()
        return os.execvpe(cmd[0], cmd, env)

    def getoutput(self, cmd):
        """
        Run command with binder and return output in a string
        """
        r, w = os.pipe()
        pid = os.fork()
        if pid:
            os.close(w)
            os.waitpid(pid, 0)
            return os.fdopen(r).read()
        else:
            os.close(r)
            os.dup2(w, sys.stdout.fileno())
            self.run(cmd)
            os.close(w)
            os._exit(0)


class OpenMP(Binding):
    """
    Class for binding OpenMP applications threads.
    OpenMP bind method will export OMP_PLACES variables.
    Numbering of processing units is using logical indexing.
    """

    def __init__(self, resource_list, num_threads=None):
        super().__init__(resource_list)
        places = [ '{{{}}}'.format(','.join([ str(pu.os_index) for pu in r.PUs ])) for r in resource_list ]
        places = '{}'.format(', '.join(places))
        self.OMP_PLACES=places
        if num_threads is not None:
            if type(num_threads) is int:
                self.OMP_NUM_THREADS=str(num_threads)
        else:
            self.OMP_NUM_THREADS=str(len(resource_list))

    def __str__(self):
        return 'OMP_NUM_THREADS:{}\nOMP_PLACES{}'.format(self.OMP_NUM_THREADS, self.OMP_PLACES)

    def run(self, cmd, num_threads=False):
        cmd = cmd.split()
        os.environ['OMP_PLACES'] = self.OMP_PLACES
        if hasattr(self, 'OMP_NUM_THREADS'):
            os.environ['OMP_NUM_THREADS'] = self.OMP_NUM_THREADS            
        os.execvpe(cmd[0], cmd, os.environ)

    ldd_regex = re.compile('(lib.*omp$)|(lib.*openmp.*)')
    @staticmethod
    def is_OpenMP_application(filename):
        libs = ldd(filename)
        return any([ OpenMP.ldd_regex.match(l) for l in libs ])

class Ptrace(Binding):
    """
    Class for binding child thread and processes.
    It will bind threads and processes as they are created with fork(), vfork()
    and clone system calls. Binding is performed in a round-robin fashion of
    topology resources as threads and processes are spawned.

    This method relies on ptrace() system call.
    The value for ptrace constant are set from ubuntu 18.04 operating system.
    This will only work if the value are correctly set for your operating system.
    """

    ptrace = ctypes.CDLL(None).ptrace

    PTRACE_TRACEME = 0
    PTRACE_EVENT_FORK = 1
    PTRACE_EVENT_VFORK = 2
    PTRACE_EVENT_CLONE = 3
    PTRACE_EVENT_STOP = 128
    PTRACE_CONT = 7
    PTRACE_DETACH = 17
    PTRACE_SEIZE = int('0x4206', 16)
    PTRACE_GETEVENTMSG = int('0x4201', 16)
    PTRACE_O_TRACECLONE = int('0x00000008', 16)
    PTRACE_O_TRACEFORK = int('0x00000002', 16)

    def __init__(self, resource_list):
        """
        Ptrace resource_list initializer is cycling on resource list in a round-robin fashion.
        """
        self.resources = cycle(resource_list)
        super().__init__(resource_list)

    def bind_next_thread(self, pid):
        bind_thread(next(self.resources), pid)

    @staticmethod
    def trace_pid(pid, fn, *args, **kwargs):
        """
        Internal method of tracer to process signals from tracee and catch clone(), fork(), vfork() syscalls()
        @arg pid is the pid of the process to trace
        @arg fn is a function that takes a pid as first argument and that will be called on this
        process and its child processes.
        @args: fn other arguments.
        @kwargs: fn other keyword arguments.
        """
        if Ptrace.ptrace(Ptrace.PTRACE_SEIZE, ctypes.c_int32(pid), None,
                         ctypes.c_uint64(Ptrace.PTRACE_O_TRACECLONE|Ptrace.PTRACE_O_TRACEFORK)) == -1:
            os.kill(pid, SIGKILL);
            raise Exception('ptrace syscall failed.')
        else:
            fn(pid, *args, **kwargs)
            os.kill(pid, SIGCONT);
        while True:
            child, status = os.waitpid(-1, 0)
            if child == pid:
                if os.WIFEXITED(status):
                    return os.WEXITSTATUS(status)
                if os.WIFSIGNALED(status):
                    return 0
            if os.WIFSTOPPED(status):
                sig = os.WSTOPSIG(status)
                if sig == SIGTRAP:
                    event = status >> 8
                    eventmsg = ctypes.c_int64(0)
                    if Ptrace.ptrace(Ptrace.PTRACE_GETEVENTMSG, child, 0, ctypes.pointer(eventmsg)) == -1:
                        print("tracer: PTRACE_GETEVENTMSG")
                        break
                    if event == (SIGTRAP|(Ptrace.PTRACE_EVENT_FORK<<8)) or event == (SIGTRAP|(Ptrace.PTRACE_EVENT_VFORK<<8)) or event == (SIGTRAP|(Ptrace.PTRACE_EVENT_CLONE<<8)):
                        fn(eventmsg.value, *args, **kwargs)
                # MPI seams to exit on this status while the others do not work.
                # os.WIFSTOPPED(4479) = True
                # os.WSTOPSIG(4479) = SIGCHLD
                elif sig == SIGCHLD and child == pid:
                    break
                if Ptrace.ptrace(Ptrace.PTRACE_CONT, child, 0, 0) == -1:
                    pass # raise Exception('PTRACE_CONT(interrupt)')

    def run(self, cmd):
        """
        Subprocess launcher enforcing binding.
        fork execvp the command line. Stop child until ptrace is started then resume child.
        @param cmd: The command line string to launch.
        """
        pid = os.fork()
        if pid == 0:
            pid = os.getpid()
            cmd = cmd.split()
            os.kill(pid, SIGSTOP)
            os.execvp(cmd[0], cmd)
            os._exit(127)
        else:
            Ptrace.trace_pid(pid, self.bind_next_thread)
            os._exit(0)

class MPI(Binding):
    ldd_regex = re.compile('(lib.*mpi$)|(lib.*mpich)')
    rank_regex = re.compile('.*MPI.*LOCAL_RANK.*')

    def __init__(self, resource_list, num_procs, env={}, launcher='mpirun'):
        Binding.__init__(self, resource_list)
        num_procs = num_procs if num_procs is not None else len(resource_list)
        for k in env.keys():
            if k in os.environ.keys():
                os.environ[k] = '{}:{}'.format(os.environ[k], env[k])
            else:
                os.environ[k] = env[k]
        if MPI.is_MPI_process():
            resource = resource_list[MPI.get_rank() % len(resource_list)]
            bind_process(resource, os.getpid())
        else:
            launcher = '{} -np {}'.format(launcher, num_procs)
            self.launcher = launcher
            self.run = lambda cmd: MPI.mpirun(launcher, cmd)

    @staticmethod
    def mpirun(launcher, cmd):
        cmd = '{} {}'.format(launcher, cmd)
        cmd = cmd.split()
        os.execvpe(cmd[0], cmd, os.environ)

    @staticmethod
    def is_MPI_application(filename):
        libs = ldd(filename)
        return any([ MPI.ldd_regex.match(l) for l in libs ])

    @staticmethod
    def is_MPI_process():
        """
        Return True if one of local rank environment variables are defined.
        """
        return any(MPI.rank_regex.match(k) for k in os.environ.keys())

    @staticmethod
    def get_rank(env=os.environ):
        """
        Return the rank of local mpi process.
        """
        return int(next(v for k,v in env.items() if MPI.rank_regex.match(k)))

class OpenMPI(MPI):
    """
    MPI binding for OpenMPI.
    """

    RESOURCE_MAP = {
        'PU': 'hwthread',
        'Core': 'core',
        'L1Cache': 'l1cache',
        'L2Cache': 'l2cache',
        # 'L3Cache': 'l3cache', # Not working
        # 'Package': 'socket', # Not working
        # 'Machine': 'board', # Not working
    }

    @staticmethod
    def _rankfile_(resources):
        """
        Return a list of strings where each item is a line of the rankfile
        binding in the order of the resource list.
        """
        hostname=gethostname()

        # If all resources are of the same type, the knob `--bind-to` will be
        # set to this resource and we just have to output slots for these
        # resources logical index.
        if all([ r.type==resources[0].type for r in resources]) and\
           resources[0].type in OpenMPI.RESOURCE_MAP.keys():
            return [ "rank {}={} slot={}".format(i,
                                                 r.hostname if hasattr(r, 'hostname') else hostname,
                                                 r.logical_index) for i, r in zip(range(len(resources)), resources) ]

    @staticmethod
    def _hostfile_(resources):
        """
        Return a list of strings where each item is a line of the rankfile
        binding in the order of the resource list.
        """
        hosts = set([r.hostname for r in resources if hasattr(r, 'hostname')])
        if len(hosts) == 0:
            hosts = { gethostname(): len([resources])}
        else:
            hosts = { h: len([r for r in resources if hasattr(r, 'hostname') and r.hostname == h ]) for h in hosts }

        return [ '{} slots={} max_slots={}'.format(h, n, n) for (h,n) in hosts.items() ]
    
    @staticmethod
    def _bindto_knob_(resources):
        """
        Returns the knob specifying the type of objects to bind to.
        If all resources are of the same type then the knob is to bind to this
        type of resource and the rankfile will be set to this resource logical 
        indexes.
        If resources are heterogeneous, then the binding is done at the 
        hardware thread granularity and the rankfile will bind hardware threads.

        OpenMPI option:
        ```
        --bind-to <arg0>      Policy for binding processes. Allowed values: none,
                      hwthread, core, l1cache, l2cache, l3cache, socket,
                      numa, board, cpu-list ("none" is the default when
                      oversubscribed, "core" is the default when np<=2,
                      and "socket" is the default when np>2). Allowed
                      qualifiers: overload-allowed, if-supported,
                      ordered
        ```
        """
        if all([ r.type==resources[0].type for r in resources]):
            try:
                return '--bind-to {}'.format(OpenMPI.RESOURCE_MAP[resources[0].type])
            except KeyError:
                pass
        return '--bind-to hwthread'
    
    def __init__(self, resource_list, num_procs=None,
                 env={},
                 knobs=[]):
        
        # Write rankfile
        f, self.rankfile = tmp(dir=os.getcwd(), text=True)
        file = os.fdopen(f, 'w')
        for l in OpenMPI._rankfile_(resource_list):
            file.write(l + '\n')
        file.close()

        # Set knobs
        knobs.append(OpenMPI._bindto_knob_(resource_list))
        launcher = 'mpirun {} -rf {}'.format(' '.join(knobs), self.rankfile)
    
        MPI.__init__(self, resource_list, num_procs, env, launcher=launcher)

    def __del__(self):
        os.remove(self.rankfile)

    def __str__(self):
        with open(self.rankfile, 'r') as f:
            return '{}\n{}'.format(self.launcher, ''.join(f.readlines()))

class MPICH(MPI):
    """
    MPI binding for MPICH.
    """
    def __init__(self, resource_list, num_procs=None, env={}):
        num_procs = num_procs if num_procs is not None else len(resource_list)
        binding = [ '+'.join([ str(pu.os_index) for pu in r.PUs]) for r in resource_list ]
        binding = 'user:{}'.format(','.join(binding))
        launcher = 'mpirun -launcher fork -bind-to {}'.format(binding)
        MPI.__init__(self, resource_list, num_procs, env, launcher)

    def __str__(self):
        return '{}'.format(self.launcher)
    
#########################################################################################

__all__ = [ 'MPI', 'OpenMP', 'OpenMPI', 'MPICH', 'Ptrace' ]

#########################################################################################

if __name__ == '__main__':
    from tmap.topology import topology
    from random import sample
    from math import ceil
    from os import _exit
    
    def test_binder(binder_name, binder, resources, cmd):
        out = binder.getoutput(cmd)
        out = out.split('\n')
        cpusets = [r.cpuset for r in resources]
        match = all([ x == y for x, y in zip(cpusets, out) ])
        if match:
            print('Test {}: success'.format(binder_name))
        else:
            print('Test {}: failure'.format(binder_name))
            print('Resources: {}'.format(resources))
            print('Expected cpusets: \n\t{}'.format('\n\t'.join(cpusets)))
            print('Got output:')
            for l in out:
                print('\t' + l)

    def test_resources(resources):
        if MPI.is_MPI_process():
            rank = MPI.get_rank()
            cmd = test_dir + os.path.sep + 'mpi'
            mpi = MPI(resources, len(resources))
            test_binder('MPI', mpi, [resources[rank % len(resources)]], cmd)
            os._exit(0)

        # Test Openmp
        cmd = test_dir + os.path.sep + 'openmp'
        binder = OpenMP(resources, num_threads=len(resources))
        test_binder('OpenMP', binder, resources, cmd)

        # Test openmp / ptrace
        cmd = test_dir + os.path.sep + 'openmp ' + str(len(resources))
        test_binder('OpenMP + ptrace', binder, resources, cmd)

        # Test OpenMPI
        cmd = test_dir + os.path.sep + 'mpi'
        binder = OpenMPI(resources, num_procs=len(resources))
        test_binder('OpenMPI', binder, resources, cmd)
    
        # Test pthread / ptrace
        # cmd = test_dir + os.path.sep + 'pthread ' + str(len(resources))
        # binder = Ptrace(resources)
        # test_binder('pthread + ptrace', binder, resources, cmd)

        # Test MPICH
        # cmd = test_dir + os.path.sep + 'mpi'
        # binder = MPICH(resources, num_procs=len(resources))
        # test_binder('MPICH', binder, resources, cmd)


    test_dir = '{}/{}/tests'.format(os.path.dirname(os.path.abspath(__file__)),
                                    os.path.pardir)
    # Build tests
    subprocess.getoutput('make -C ' + test_dir)

    for t in OpenMPI.RESOURCE_MAP.keys():
        resources = [ n for n in topology if hasattr(n, 'type') and n.type == t ]
        resources = sample(resources, ceil(len(resources)/2))
        test_resources(resources)
    resources = [ n for n in topology if hasattr(n, 'type') and n.type in OpenMPI.RESOURCE_MAP.keys() ]
    resources = sample(resources, min(len(resources), 8))
    test_resources(resources)
