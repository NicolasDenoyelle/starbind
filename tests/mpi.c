#include <stdio.h>
#include <stdlib.h>
#include <mpi.h>

void* print_cpubind(void *);

int main(int argc, char **argv) {
	if (MPI_Init(&argc, &argv) != MPI_SUCCESS){
		perror("MPI_Init");
		return -1;
	}

	print_cpubind(NULL);

	MPI_Finalize();
	return 0;
}
