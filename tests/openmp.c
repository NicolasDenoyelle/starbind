#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

void* print_cpubind(void *);

int main(int argc, char **argv) {
	if (argc < 2) {
		fprintf(stderr, "%s <nthreads>\n", argv[0]);
		return 1;
	}

	int i = 0, n = atoi(argv[1]);
	omp_set_num_threads(n);

#pragma omp parallel shared(i)
	{
		int tid = omp_get_thread_num();
		while(i != tid) {}
		print_cpubind(NULL);
		i++;
	}
	return 0;
}
