#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

void* print_cpubind(void*);

int main(int argc, char **argv) {
	int i = 0;
	if (argc > 1)
		omp_set_num_threads(atoi(argv[1]));
	
#pragma omp parallel shared(i)
	{
		int tid = omp_get_thread_num();
#pragma omp barrier
		while(i != tid) {}
		print_cpubind(NULL);
		i++;
	}
	return 0;
}
