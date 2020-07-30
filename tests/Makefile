##
# StarBind Tests
#
# @file
# @version 0.1

CC=gcc
MPICC=mpicc
CFLAGS=-Wall -Wextra -Werror
LDFLAGS=-L/usr/lib/x86_64-linux-gnu -lhwloc

SRC=get_cpubind.c
BIN=pthread openmp mpi
OBJ=$(patsubst %.c, %.o, $(SRC))

.PHONY: all clean

all: $(OBJ) $(BIN)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

pthread: pthread.o get_cpubind.o
	$(CC) $(CFLAGS) $^ -o $@ $(LDFLAGS) -lpthread

openmp: openmp.c get_cpubind.o
	$(CC) $(CFLAGS) $^ -o $@ $(LDFLAGS) -fopenmp

mpi: mpi.c get_cpubind.o
	$(MPICC) $(CFLAGS) $^ -o $@ $(LDFLAGS)

clean:
	rm -f $(OBJ) $(BIN)
# end
