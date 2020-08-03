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
from random import shuffle
from tempfile import TemporaryFile as tmp
from itertools import cycle
from signal import SIGSTOP, SIGCONT, SIGTRAP, SIGKILL, SIGCHLD

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

    def __init__(self, resource_list, num_threads=None):
        super().__init__(resource_list)
        places = [ '{{{}}}'.format(','.join([ str(pu.logical_index) for pu in r.PUs ])) for r in resource_list ]
        places = '{}'.format(', '.join(places))
        self.OMP_PLACES=places
        if num_threads is not None:
            if type(num_threads) is int:
                self.OMP_NUM_THREADS=str(num_threads)
            else:
                self.OMP_NUM_THREADS=str(len(resource_list))

    def run(self, cmd, num_threads=False):
        cmd = cmd.split()
        env = { 'OMP_PLACES': self.OMP_PLACES }
        if hasattr(self, 'OMP_NUM_THREADS'):
            env['OMP_NUM_THREADS'] = self.OMP_NUM_THREADS
        os.execvpe(cmd[0], cmd, env)

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

    def bind_next_thread(self, pid):
        bind_thread(next(self.resource_list), pid)

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

    def __init__(self, resource_list, num_procs=None, env={}):
        super().__init__(resource_list)
        for k in env.keys():
            if k in os.environ.keys():
                os.environ[k] = '{}:{}'.format(os.environ[k], env[k])
            else:
                os.environ[k] = env[k]

        if MPI.is_MPI_process():
            self.resource = resource_list[MPI.get_rank() % len(resource_list)]
            self.run = self.run_process
        elif num_procs is not None:
            self.pids = []
            if type(num_procs) is int:
                self.num_procs=num_procs
            else:
                self.num_procs=len(resource_list)
            self.run = self.mpirun

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

    ldd_regex = re.compile('(lib.*mpi$)|(lib.*mpich)')
    @staticmethod
    def is_MPI_application(filename):
        libs = ldd(filename)
        return any([ MPI.ldd_regex.match(l) for l in libs ])

    @staticmethod
    def get_rank(env=os.environ):
        """
        Return the rank of local mpi process.
        """
        rankid = next(id for id in MPI.rankid_env if id in env.keys())
        return int(env[rankid])


    def try_bind_process(self, pid, retry = 4):
        """
        If mpi process, bind pid
        """
        # Get process environment
        env = open('/proc/{}/environ'.format(pid))
        env = env.readline()
        env = env.split('\x00')
        env = [ l.split('=') for l in env ]
        env = { i[0]: i[1] if len(i) > 1 else '' for i in env }

        # Look in environment if this pid is a mpi process
        try:
            rank = MPI.get_rank(env)
            resource = self.resource_list[rank % len(self.resource_list)]
            bind_process(resource, pid)
            return True
        except StopIteration:
            return False

    def mpirun(self, cmd, launcher='mpirun'):
        cmd = 'mpirun -np {} {}'.format(self.num_procs, cmd)
        pid = os.fork()
        if pid == 0:
            pid = os.getpid()
            cmd = cmd.split()
            os.execvpe(cmd[0], cmd, os.environ)
            os._exit(127)
        else:
            Ptrace.trace_pid(pid, self.try_bind_process)
            os._exit(0)

    def run_process(self, cmd, launcher='mpirun'):
        bind_process(self.resource, os.getpid())
        cmd = cmd.split()
        os.execvp(cmd[0], cmd)

#########################################################################################

__all__ = [ 'OpenMP', 'MPI', 'Ptrace' ]

#########################################################################################

if __name__ == '__main__':
    from tmap.topology import topology

    backends = { 'OpenMP': OpenMP, 'MPI': MPI, 'ptrace': Ptrace }

    def test_binder(binder_name, binder, resources, cmd):
        out = binder.getoutput(cmd)
        out = out.split('\n')
        cpusets = [r.cpuset for r in resources]
        match = all([ x == y for x, y in zip(cpusets, out) ])
        if match:
            print('Test {}: success'.format(binder_name))
        else:
            print('Test {}: failure'.format(binder_name))
            print(cpusets)
            for l in out:
                print(l)

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
    cmd = test_dir + os.path.sep + 'openmp'
    binder = OpenMP(resources, num_threads=len(resources))
    test_binder('OpenMP', binder, resources, cmd)

    # Test pthread / ptrace
    cmd = test_dir + os.path.sep + 'pthread ' + str(len(resources))
    binder = Ptrace(resources)
    test_binder('pthread + ptrace', binder, resources, cmd)

    # Test openmp / ptrace
    cmd = test_dir + os.path.sep + 'openmp ' + str(len(resources))
    test_binder('OpenMP + ptrace', binder, resources, cmd)

    # Test MPI / ptrace
    cmd = test_dir + os.path.sep + 'mpi'
    binder = MPI(resources, num_procs=len(resources))
    test_binder('MPI + ptrace', binder, resources, cmd)
