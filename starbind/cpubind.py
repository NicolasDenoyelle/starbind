###############################################################################
# Copyright 2020 UChicago Argonne, LLC.
# (c.f. AUTHORS, LICENSE)
# SPDX-License-Identifier: BSD-3-Clause
##############################################################################

import os
import sys
import ctypes
import subprocess
import re
from random import shuffle
from tempfile import TemporaryFile as tmp
from itertools import cycle
from signal import SIGSTOP, SIGCONT, SIGTRAP, SIGKILL

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

    def run(self, cmd):
        """
        Subprocess launcher enforcing binding.
        @param cmd: The command line string to launch.
        """
        cmd = cmd.split()
        return excevp(cmd[0], cmd)

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

    ldd_regex=re.compile('(lib.*omp$)|(.*openmp.*)')

    def run(self, cmd):
        places = [ '{{{}}}'.format(','.join([ str(pu.logical_index) for pu in r.PUs ])) for r in self.resource_list ]
        places = '{}'.format(', '.join(places))
        cmd = cmd.split()
        os.execvpe(cmd[0], cmd, {'OMP_PLACES': places})

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
    PTRACE_CONT = 7
    PTRACE_SEIZE = int('0x4206', 16)
    PTRACE_GETEVENTMSG = int('0x4201', 16)
    PTRACE_O_TRACECLONE = int('0x00000008', 16)
    PTRACE_O_TRACEFORK = int('0x00000002', 16)

    def __init__(self, resource_list):
        """
        Ptrace resource_list initializer is cycling on resource list in a round-robin fashion.
        """
        self.resource_list = cycle(resource_list)

    def _trace_pid_(self, pid):
        """
        Internal method of tracer to process signals from tracee and catch clone(), fork(), vfork() syscalls()
        """
        if Ptrace.ptrace(Ptrace.PTRACE_SEIZE, pid, 0, (Ptrace.PTRACE_O_TRACECLONE|Ptrace.PTRACE_O_TRACEFORK)) == -1:
            os.kill(pid, SIGKILL);
            raise Exception('ptrace syscall failed.')
        else:
            bind_thread(next(self.resource_list), pid)
            os.kill(pid, SIGCONT);
        while True:
            child, status = os.waitpid(-1, 0)
            if os.WIFEXITED(status) and child == pid:
                return os.WEXITSTATUS(status)
            if os.WIFSIGNALED(status) and child == pid:
                return 0
            if os.WIFSTOPPED(status):
                sig = os.WSTOPSIG(status)
                if sig == SIGTRAP:
                    event = status >> 8
                    eventmsg = ctypes.c_int64(0)
                    if Ptrace.ptrace(Ptrace.PTRACE_GETEVENTMSG, child, 0, ctypes.pointer(eventmsg)) == -1:
                        print("tracer: PTRACE_GETEVENTMSG")
                        continue
                    if event == (SIGTRAP|(Ptrace.PTRACE_EVENT_FORK<<8)) or event == (SIGTRAP|(Ptrace.PTRACE_EVENT_VFORK<<8)) or event == (SIGTRAP|(Ptrace.PTRACE_EVENT_CLONE<<8)):
                        bind_thread(next(self.resource_list), eventmsg.value)
                if Ptrace.ptrace(Ptrace.PTRACE_CONT, child, 0, 0) == -1:
                    raise Exception('PTRACE_CONT(interrupt)')

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
            self._trace_pid_(pid)
            os._exit(0)
            
class MPI(Binding):
    """
    MPI Binding.
    Look for 'MPI_LOCALRANKID', 'OMPI_COMM_WORLD_LOCAL_RANK' in environment.
    If one of these variables is defined then MPI binding with use the local
    rank as an index among resources list to bind the local process.
    """

    """
    Local rank environment variables.
    """
    rankid_env = [ 'MPI_LOCALRANKID', 'OMPI_COMM_WORLD_LOCAL_RANK' ]

    @staticmethod
    def is_MPI_process():
        """
        Return True if one of local rank environment variables are defined.
        """
        try:
            next(id for id in MPI.rankid_env if id in os.environ.keys())
            return True
        except StopIteration:
            return False

    @staticmethod
    def get_rank():
        """
        Return the rank of local mpi process.
        """
        try:
            rankid = next(id for id in MPI.rankid_env if id in os.environ.keys())
        except StopIteration:
            raise Exception('Run inside mpi command line.')
        return int(os.environ[rankid])

    def __init__(self, resource_list):
        self.resource = resource_list[MPI.get_rank() % len(resource_list)]

    def run(self, cmd):
        bind_process(self.resource, os.getpid())
        cmd = cmd.split()
        os.execvp(cmd[0], cmd)

#########################################################################################

__all__ = [ 'OpenMP', 'MPI', 'Ptrace' ]

#########################################################################################

if __name__ == '__main__':
    from tmap.topology import topology

    backends = { 'OpenMP': OpenMP, 'MPI': MPI, 'ptrace': Ptrace }
    
    def test_binder(binder_name, resources, cmd):
        binder = backends[binder_name](resources)
        out = binder.getoutput(cmd)
        out = out.split('\n')
        cpusets = [r.cpuset for r in resources]
        match = all([ x == y for x, y in zip(cpusets, out) ])
        if match:
            print('Test {}: success'.format(binder_name))
        else:
            print('Test {}: failure'.format(binder_name))
            for x, y in zip(cpusets, out):
                print('{} {}'.format(x,y))

    test_dir = '{}/{}/tests'.format(os.path.dirname(os.path.abspath(__file__)),
                                    os.path.pardir)
    resources = [ n for n in topology if n.type.upper() == 'CORE' ]

    if MPI.is_MPI_process():
        rank =MPI.get_rank()
        cmd = test_dir + os.path.sep + 'mpi'
        test_binder('MPI', [resources[rank % len(resources)]], cmd)
        os._exit(0)
        
    shuffle(resources)
    
    # Build tests
    subprocess.getoutput('make -C ' + test_dir)

    # Test Openmp
    cmd = test_dir + os.path.sep + 'openmp ' + str(len(resources))
    test_binder('OpenMP', resources, cmd)

    # Test pthread / ptrace
    cmd = test_dir + os.path.sep + 'pthread ' + str(len(resources))
    test_binder('ptrace', resources, cmd)

    # Test openmp / ptrace
    cmd = test_dir + os.path.sep + 'openmp ' + str(len(resources))
    test_binder('ptrace', resources, cmd)
