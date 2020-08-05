#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <mpi.h>

void* print_cpubind(void *);

int main(int argc, char **argv) {
	int n, rank;
	MPI_Status status;

	if (MPI_Init(&argc, &argv) != MPI_SUCCESS){
		perror("MPI_Init");
		return -1;
	}

	MPI_Comm_size(MPI_COMM_WORLD, &n);
	MPI_Comm_rank(MPI_COMM_WORLD, &rank);

	if (rank == 0) {
		print_cpubind(NULL);
		rank++;
		MPI_Send(&rank, 1, MPI_INT, rank, 0, MPI_COMM_WORLD);
	} else if (rank+1 < n) {
		MPI_Recv(&n, 1, MPI_INT, rank-1, 0, MPI_COMM_WORLD, &status);
		print_cpubind(NULL);
		rank++;
		MPI_Send(&rank, 1, MPI_INT, rank, 0, MPI_COMM_WORLD);
	} else {
		MPI_Recv(&n, 1, MPI_INT, rank-1, 0, MPI_COMM_WORLD, &status);
		print_cpubind(NULL);
	}

	MPI_Finalize();
	return 0;
}
