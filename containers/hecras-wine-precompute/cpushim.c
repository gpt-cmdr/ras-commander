/*
 * cpushim.c - LD_PRELOAD shim that makes sched_getcpu() agree with Wine's
 * processor count when a job runs in a CPU set that does not start at 0.
 *
 * In a 2-CPU Slurm/cgroup cpuset on host CPUs 4-5, Wine 11 reports
 * NumberOfProcessors = 2 but GetCurrentProcessorNumber() returns the raw host
 * ids 4 and 5 (Wine returns sched_getcpu()). Windows guarantees 0..N-1. The
 * .NET 4.8 runtime used by RasProcess.exe indexes per-processor state with that
 * number, and HEC-RAS 6.6 preprocessing then fails intermittently with
 * 0xC0000005 in clr.dll.
 *
 * This shim returns the CPU's index within the process affinity mask
 * (host CPUs 4,5 -> 0,1). The map is built once, on first use; CPUs outside
 * the mask are passed through unchanged. prepare.py and the portable
 * executor (ras_commander.remote.execute_request) preload it for the Wine
 * processes only, from the path in RAS_COMMANDER_WINE_CPU_SHIM.
 *
 * Build: cc -shared -fPIC -O2 -o cpushim.so cpushim.c -ldl -pthread
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <sched.h>
#include <pthread.h>

static int (*real_getcpu)(void);
static pthread_once_t map_once = PTHREAD_ONCE_INIT;
static short cpu_index[CPU_SETSIZE];

static void build_map(void)
{
    cpu_set_t set;
    real_getcpu = (int (*)(void))dlsym(RTLD_NEXT, "sched_getcpu");
    int c, n = 0;
    for (c = 0; c < CPU_SETSIZE; c++) cpu_index[c] = -1;
    if (sched_getaffinity(0, sizeof(set), &set) == 0)
        for (c = 0; c < CPU_SETSIZE; c++)
            if (CPU_ISSET(c, &set)) cpu_index[c] = (short)n++;
}

int sched_getcpu(void)
{
    int cpu;
    pthread_once(&map_once, build_map);
    cpu = real_getcpu ? real_getcpu() : -1;
    if (cpu >= 0 && cpu < CPU_SETSIZE && cpu_index[cpu] >= 0) return cpu_index[cpu];
    return cpu;
}
