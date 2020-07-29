#include <hwloc.h>
#include <sys/types.h>

#define SIZE 64

void* print_cpubind(void *unused) {
	(void) unused;

	int64_t err = 0;
	hwloc_cpuset_t cpuset;
	hwloc_topology_t topology;
	char cpuset_str[SIZE];

	if (hwloc_topology_init(&topology) != 0) {
		perror("hwloc_topology_init");
		return (void*)-1;
	}

	if (hwloc_topology_load(topology) != 0) {
		perror("hwloc_topology_load");
		return (void*)-1;
	}

	cpuset = hwloc_bitmap_alloc();
	if (cpuset == NULL) {
		err = -1;
		goto exit;
	}

	if(hwloc_get_cpubind(topology, cpuset, HWLOC_CPUBIND_THREAD) == -1) {
		err = -1;
		perror("hwloc_get_cpubind");
		goto exit_with_cpuset;
	}

	if (hwloc_bitmap_snprintf(cpuset_str, SIZE, cpuset) == -1) {
		err = -1;
		goto exit_with_cpuset;
	}

	printf("%s\n", cpuset_str);

exit_with_cpuset:
	hwloc_bitmap_free(cpuset);
exit:
	hwloc_topology_destroy(topology);
	return (void*)err;
}
