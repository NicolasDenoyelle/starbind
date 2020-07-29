#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <unistd.h>
#include <pthread.h>

pthread_barrier_t barrier;
pthread_t *thread = NULL;

void* print_cpubind(void *);

void* work(void *arg) {
	(void)arg;
	pthread_barrier_wait(&barrier);
	while(*thread != pthread_self()) {}
	print_cpubind(NULL);
	thread++;
	return NULL;
}

int main(int argc, char **argv) {
	if (argc < 2) {
		fprintf(stderr, "%s <nthreads>\n", argv[0]);
		return 1;
	}

	int64_t err = 0, i = 0, n = atoi(argv[1])-1;
	pthread_t threads[n];
	pthread_barrier_init(&barrier, NULL, n+1);

	print_cpubind(NULL);
	for (i = 0; i < n; i++)
		pthread_create(threads+i, NULL, work, NULL);
	thread = threads;
	pthread_barrier_wait(&barrier);

	while (i--)
		pthread_join(threads[i], NULL);
	pthread_barrier_destroy(&barrier);
	return err;
}
