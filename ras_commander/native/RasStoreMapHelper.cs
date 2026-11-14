using System;
using System.IO;
using System.Reflection;
using System.Xml;
using System.Linq.Expressions;
using System.Threading;
using System.Runtime.ExceptionServices;
using System.Globalization;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.ComponentModel;
using System.Diagnostics;

/// <summary>
/// Headless stored map generator that respects rendering mode.
/// Designed to replace RasProcess.exe StoreAllMaps which ignores RenderMode in 6.x.
///
/// Uses reflection for all RasMapperLib calls to work across HEC-RAS versions
/// (6.0, 6.1, 6.2, 6.3.1, 6.5, 6.6, etc.) without recompilation.
///
/// Usage:
///   StoreAllMaps (legacy): RasStoreMapHelper.exe hecrasDir renderMode rasmapFile [resultHdf]
///   StoreAllMaps (explicit): RasStoreMapHelper.exe hecrasDir renderMode StoreAllMaps rasmapFile [resultHdf]
///   StoreMap (individual):  RasStoreMapHelper.exe hecrasDir renderMode StoreMap mapType resultHdf profileName [outputBasePath]
///
/// mapType values: WSEL, Depth, Velocity, DepthTimesVelocity, DepthTimesVelocitySquared,
///                 ProfileMap:xmlName (e.g. ProfileMap:froude, ProfileMap:Shear)
/// </summary>
class RasStoreMapHelper
{
    static string _hecrasDir;
    static Assembly _asm;
    static bool _polygonSerial;
    static bool _jobMemoryLimited;
    static bool _diagnosticsEnabled;
    static int _diagnosticCount;
    [ThreadStatic] static bool _writingDiagnostic;
    [ThreadStatic] static bool _handlingDiagnosticException;
    const int DiagnosticLimit = 64;
    const int DiagnosticLengthLimit = 16384;

    // This unnamed, non-inheritable handle belongs only to this helper. Children
    // inherit job membership, never the handle that controls failure cleanup.
    sealed class MemoryJob
    {
        const uint JobMemory = 0x200, KillOnClose = 0x2000, ActiveLimit = 8;
        IntPtr handle;
        bool assigned;
        [StructLayout(LayoutKind.Sequential)]
        struct BasicLimits
        {
            public long ProcessTime, JobTime;
            public uint Flags;
            public UIntPtr MinimumWorkingSet, MaximumWorkingSet;
            public uint ActiveProcesses;
            public UIntPtr Affinity;
            public uint Priority, Scheduling;
        }
        [StructLayout(LayoutKind.Sequential)]
        struct IoCounters { public ulong A, B, C, D, E, F; }
        [StructLayout(LayoutKind.Sequential)]
        struct ExtendedLimits
        {
            public BasicLimits Basic;
            public IoCounters Io;
            public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
        }
        [StructLayout(LayoutKind.Sequential)]
        struct Accounting
        {
            public long UserTime, KernelTime, PeriodUserTime, PeriodKernelTime;
            public uint PageFaults, TotalProcesses, ActiveProcesses, TerminatedProcesses;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimits limits, uint length);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool QueryInformationJobObject(IntPtr job, int kind, ref ExtendedLimits limits, uint length, IntPtr returned);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool QueryInformationJobObject(IntPtr job, int kind, ref Accounting accounting, uint length, IntPtr returned);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool member);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool TerminateJobObject(IntPtr job, uint exitCode);

        static void Check(bool success, string operation)
        {
            if (!success) throw new Win32Exception(Marshal.GetLastWin32Error(), operation);
        }
        ExtendedLimits Limits()
        {
            ExtendedLimits limits = new ExtendedLimits();
            Check(QueryInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf(typeof(ExtendedLimits)), IntPtr.Zero), "Query job memory limits");
            return limits;
        }
        public bool Contains(Process process)
        {
            bool member;
            Check(IsProcessInJob(process.Handle, handle, out member), "Query child job membership");
            return member;
        }
        public MemoryJob(int mib)
        {
            if (Environment.OSVersion.Platform != PlatformID.Win32NT || IntPtr.Size != 8)
                throw new PlatformNotSupportedException("Job memory limit requires 64-bit native Windows");
            handle = CreateJobObject(IntPtr.Zero, null);
            if (handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "Create memory job");
            try
            {
                ExtendedLimits limits = new ExtendedLimits();
                limits.Basic.Flags = JobMemory | KillOnClose;
                limits.JobMemory = new UIntPtr(checked((ulong)mib * 1024UL * 1024UL));
                Check(SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf(typeof(ExtendedLimits))), "Set job memory limit");
                using (Process self = Process.GetCurrentProcess())
                {
                    Check(AssignProcessToJobObject(handle, self.Handle), "Assign helper to memory job (nested jobs must be supported)");
                    assigned = true;
                    if (!Contains(self)) throw new InvalidOperationException("Helper memory job membership readback failed");
                }
                ExtendedLimits actual = Limits();
                if (actual.JobMemory != limits.JobMemory || actual.Basic.Flags != limits.Basic.Flags)
                    throw new InvalidOperationException("Memory job limit/flags readback failed");
                Console.WriteLine("NATIVE_JOB_MEMORY_LIMIT_EFFECTIVE_MIB=" + mib);
                Console.WriteLine("NATIVE_JOB_MEMORY_FLAGS=" + actual.Basic.Flags);
                Console.WriteLine("NATIVE_JOB_MEMORY_SELF_MEMBER=True");
                Console.WriteLine("NATIVE_JOB_MEMORY_CLR=" + Environment.Version);
            }
            catch { Close(false); throw; }
        }
        public void Close(bool successful)
        {
            if (handle == IntPtr.Zero) return;
            if (assigned)
            {
                try { Console.WriteLine("NATIVE_JOB_MEMORY_PEAK_COMMIT_BYTES=" + Limits().PeakJobMemory.ToUInt64().ToString(CultureInfo.InvariantCulture)); }
                catch (Exception error) { Console.Error.WriteLine("NATIVE_JOB_MEMORY_PEAK_QUERY_FAILED=" + error.Message); }
            }
            if (successful && assigned)
            {
                Accounting accounting = new Accounting();
                Stopwatch cleanupWait = Stopwatch.StartNew();
                do
                {
                    Check(QueryInformationJobObject(handle, 1, ref accounting, (uint)Marshal.SizeOf(typeof(Accounting)), IntPtr.Zero), "Query live job processes");
                    if (accounting.ActiveProcesses == 1) break;
                    // Process exit can be signaled before job accounting has
                    // retired the exited child. Never clear kill-on-close early.
                    Thread.Sleep(10);
                } while (cleanupWait.ElapsedMilliseconds < 5000);
                if (accounting.ActiveProcesses != 1)
                    throw new InvalidOperationException("Cannot complete capped helper while job descendants remain alive");
                ExtendedLimits limits = Limits();
                // Prevent a late child spawn before dropping kill-on-close.
                limits.Basic.Flags |= ActiveLimit;
                limits.Basic.ActiveProcesses = 1;
                Check(SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf(typeof(ExtendedLimits))), "Seal completed job against new children");
                limits.Basic.Flags &= ~KillOnClose;
                Check(SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf(typeof(ExtendedLimits))), "Clear completed job kill-on-close");
                if (Limits().Basic.Flags != limits.Basic.Flags)
                    throw new InvalidOperationException("Completed job cleanup readback failed");
                Console.WriteLine("NATIVE_JOB_MEMORY_CHILDREN_EXITED=True");
            }
            Console.Out.Flush(); Console.Error.Flush();
            // Closing a kill-on-close job can report exit0 for its own process.
            // Preserve an unambiguous failing status while terminating only
            // this helper's unnamed job (including all its descendants).
            if (!successful && assigned)
                Check(TerminateJobObject(handle, 99), "Terminate failed helper memory job");
            IntPtr closing = handle; handle = IntPtr.Zero;
            Check(CloseHandle(closing), "Close helper memory job");
        }
    }

    static int ParseMemoryMiB(string value)
    {
        int result;
        if (!Int32.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out result) || result < 1 || result > 1048576)
            throw new ArgumentException("native_job_memory_limit_mb must be an integer from 1 to 1048576 MiB");
        return result;
    }

    static string MemoryRuntimeHash(string path)
    {
        using (SHA256 hash = SHA256.Create())
        using (FileStream file = File.OpenRead(path))
            return BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
    }

    static void ValidateMemoryRuntime()
    {
        string mapper = MemoryRuntimeHash(Path.Combine(_hecrasDir, "RasMapperLib.dll"));
        string utility = MemoryRuntimeHash(Path.Combine(_hecrasDir, "Utility.Core.dll"));
        string merge = MemoryRuntimeHash(Path.Combine(_hecrasDir, "RasProcess.exe"));
        string version;
        if (mapper == "ffb8eb7ec518f6bfd0f4c5d0e9f889381477270a869d801b02103d7aad18f023" &&
            utility == "ac5a1aed50c2f3bd52a7ffee62c0b87849d71a7883197908e92b4d2b479f8745" &&
            merge == "dbfcbe0289bcfc80f95efe4a6b6105dee4413d9fbc5bef46fcec339cdb9b3cf0") version = "6.6";
        else if (mapper == "8f246aae48a5833288d12568203919693cc15992d750514058467916a203fd7e" &&
            utility == "a4267f07ca18fef84f5ac6b1c82f5d62ee6f46dd95033e281b61af96d0c0f327" &&
            merge == "accab6ee51e8617f81f0b2ca7a488011d3f3d1eb31a58ab50a9e825c9be3292e") version = "7.0.1";
        else throw new InvalidOperationException("Job memory cap requires an independently verified native launch chain");
        Assembly loaded = Assembly.LoadFrom(Path.Combine(_hecrasDir, "Utility.Core.dll"));
        if (!String.Equals(Path.GetFullPath(loaded.Location), Path.GetFullPath(Path.Combine(_hecrasDir, "Utility.Core.dll")), StringComparison.OrdinalIgnoreCase) ||
            MemoryRuntimeHash(loaded.Location) != utility)
            throw new InvalidOperationException("Loaded Utility.Core does not match the admitted memory containment runtime");
        Console.WriteLine("NATIVE_JOB_MEMORY_RUNTIME_VERSION=" + version);
        Console.WriteLine("NATIVE_JOB_MEMORY_UTILITY_CORE_SHA256=" + utility);
        Console.WriteLine("NATIVE_JOB_MEMORY_MAPPER_SHA256=" + mapper);
        Console.WriteLine("NATIVE_JOB_MEMORY_MERGE_SHA256=" + merge);
        Console.WriteLine("NATIVE_JOB_MEMORY_CONTAINMENT_POLICY=direct_create_process_no_shell_no_breakaway");
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr VirtualAlloc(IntPtr address, UIntPtr bytes, uint allocation, uint protection);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool VirtualFree(IntPtr address, UIntPtr bytes, uint freeType);

    static int MemoryProbeChild(string scenario, int mib)
    {
        if (mib < 96 || mib > 256 || (scenario != "Sleep" && scenario != "Allocate"))
            throw new ArgumentException("Synthetic child probes are bounded to 96..256 MiB");
        Console.WriteLine("NATIVE_JOB_MEMORY_CHILD_PID=" + Process.GetCurrentProcess().Id);
        Console.Out.Flush();
        if (scenario == "Sleep") { Thread.Sleep(120000); return 0; }
        var blocks = new System.Collections.Generic.List<IntPtr>();
        try
        {
            for (int i = 0; i <= mib / 4; i++)
            {
                IntPtr block = VirtualAlloc(IntPtr.Zero, new UIntPtr(4U * 1024U * 1024U), 0x3000, 4);
                if (block == IntPtr.Zero)
                {
                    Console.WriteLine("NATIVE_JOB_MEMORY_ALLOCATION_REFUSED=True");
                    Console.WriteLine("NATIVE_JOB_MEMORY_CHILD_COMMITTED_MIB=" + (blocks.Count * 4));
                    return 0;
                }
                blocks.Add(block);
            }
            return 6;
        }
        finally { foreach (IntPtr block in blocks) VirtualFree(block, UIntPtr.Zero, 0x8000); }
    }

    static int RunMemoryProbe(string[] args, MemoryJob job, int mib)
    {
        foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
            if (assembly.GetName().Name == "RasMapperLib")
                throw new InvalidOperationException("Job memory probe must not load HEC-RAS");
        Console.WriteLine("NATIVE_JOB_MEMORY_HEC_ASSEMBLIES_LOADED=False");
        Console.WriteLine("NATIVE_JOB_MEMORY_CLR_ASSEMBLY=" + typeof(object).Assembly.Location);
        if (args.Length != 4 && (args.Length != 6 || args[4] != "--ProbeScenario"))
            throw new ArgumentException("Invalid memory probe arguments");
        string scenario = args.Length == 6 && args[4] == "--ProbeScenario" ? args[5] : "Readback";
        if (scenario == "Readback") return 0;
        if (scenario == "Nested")
        {
            MemoryJob nested = new MemoryJob(mib);
            try { Console.WriteLine("NATIVE_JOB_MEMORY_NESTED=True"); }
            finally { nested.Close(true); }
            return 0;
        }
        if (scenario != "Aggregate" && scenario != "ChildOnly" && scenario != "Timeout" && scenario != "Failure")
            throw new ArgumentException("Unknown memory probe scenario");
        if (mib < 96 || mib > 256)
            throw new ArgumentException("Synthetic allocating probes are bounded to 96..256 MiB");
        IntPtr parentBlock = IntPtr.Zero;
        try
        {
            if (scenario == "Aggregate")
            {
                parentBlock = VirtualAlloc(IntPtr.Zero, new UIntPtr(16U * 1024U * 1024U), 0x3000, 4);
                if (parentBlock == IntPtr.Zero) throw new InvalidOperationException("Probe parent commitment refused");
                Console.WriteLine("NATIVE_JOB_MEMORY_PARENT_COMMITTED_MIB=16");
            }
            ProcessStartInfo info = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location,
                "--Mode JobMemoryLimitChild " + (scenario == "Aggregate" || scenario == "ChildOnly" ? "Allocate" : "Sleep") + " " + mib);
            info.UseShellExecute = false; info.CreateNoWindow = true;
            info.RedirectStandardOutput = true; info.RedirectStandardError = true;
            using (Process child = Process.Start(info))
            {
                if (!job.Contains(child)) throw new InvalidOperationException("Probe child escaped memory job");
                Console.WriteLine("NATIVE_JOB_MEMORY_CHILD_MEMBER=True");
                Console.WriteLine("NATIVE_JOB_MEMORY_PROBE_CHILD_PID=" + child.Id);
                Console.Out.Flush();
                if (scenario == "Timeout") { Thread.Sleep(120000); return 7; }
                if (scenario == "Failure") return 5;
                string output = child.StandardOutput.ReadToEnd();
                string error = child.StandardError.ReadToEnd();
                if (!child.WaitForExit(10000)) throw new TimeoutException("Memory probe child did not exit");
                Console.Write(output); Console.Error.Write(error);
                if (child.ExitCode != 0 || output.IndexOf("NATIVE_JOB_MEMORY_ALLOCATION_REFUSED=True", StringComparison.Ordinal) < 0)
                    throw new InvalidOperationException("Aggregate memory refusal not observed");
            }
            return 0;
        }
        finally { if (parentBlock != IntPtr.Zero) VirtualFree(parentBlock, UIntPtr.Zero, 0x8000); }
    }

    static void WriteDiagnostic(string label, string text)
    {
        if (!_diagnosticsEnabled || _writingDiagnostic) return;
        _writingDiagnostic = true;
        try
        {
            int count = Interlocked.Increment(ref _diagnosticCount);
            if (count > DiagnosticLimit) return;
            if (text.Length > DiagnosticLengthLimit)
                text = text.Substring(0, DiagnosticLengthLimit) + " [truncated]";
            Console.Error.WriteLine("NATIVE_DIAGNOSTIC_" + label + ": " + text);
            if (count == DiagnosticLimit)
                Console.Error.WriteLine("NATIVE_DIAGNOSTIC_LIMIT: further diagnostics suppressed");
        }
        catch { /* Diagnostics must not change command success or failure. */ }
        finally { _writingDiagnostic = false; }
    }

    static void OnFirstChanceException(object sender, FirstChanceExceptionEventArgs args)
    {
        if (_writingDiagnostic || _handlingDiagnosticException ||
            Interlocked.CompareExchange(ref _diagnosticCount, 0, 0) >= DiagnosticLimit) return;
        Exception error = args.Exception;
        AggregateException aggregate = error as AggregateException;
        if (aggregate == null && error.InnerException == null) return;
        _handlingDiagnosticException = true;
        try
        {
            WriteDiagnostic("EXCEPTION", (aggregate != null ? aggregate.Flatten() : error).ToString());
        }
        catch { /* A diagnostic formatting failure must not escape the handler. */ }
        finally { _handlingDiagnosticException = false; }
    }

    static Assembly ResolveAssembly(object sender, ResolveEventArgs e)
    {
        string name = new AssemblyName(e.Name).Name;
        string path = Path.Combine(_hecrasDir, name + ".dll");
        if (File.Exists(path))
            return Assembly.LoadFrom(path);
        return null;
    }

    // Applied inside the child before loading any vendor mapping assembly.
    // The parent's affinity and unrelated helpers are never modified.
    static bool ConfigureNativeCpuLimit()
    {
        string setting = Environment.GetEnvironmentVariable("RAS_COMMANDER_STORE_MAP_CPU_LIMIT");
        if (String.IsNullOrEmpty(setting)) return true;
        try
        {
            int requested;
            if (!Int32.TryParse(setting, out requested) || requested < 1 || requested > 64)
                throw new ArgumentException("native_cpu_limit must be between 1 and 64");
            using (System.Diagnostics.Process process = System.Diagnostics.Process.GetCurrentProcess())
            {
                ulong inherited = unchecked((ulong)process.ProcessorAffinity.ToInt64());
                ulong selected = 0;
                int count = 0;
                for (int bit = 0; bit < 64 && count < requested; bit++)
                {
                    ulong mask = 1UL << bit;
                    if ((inherited & mask) != 0) { selected |= mask; count++; }
                }
                if (count != requested)
                    throw new ArgumentException("native_cpu_limit exceeds inherited allowed CPUs");
                process.ProcessorAffinity = new IntPtr(unchecked((long)selected));
                if (unchecked((ulong)process.ProcessorAffinity.ToInt64()) != selected)
                    throw new InvalidOperationException("Native helper CPU affinity verification failed");
                int workerMinimum, ioMinimum;
                ThreadPool.GetMinThreads(out workerMinimum, out ioMinimum);
                Console.WriteLine("Native CPU affinity: inherited=0x{0:X}; selected=0x{1:X}; limit={2}; thread_pool_min={3}/{4}", inherited, selected, requested, workerMinimum, ioMinimum);
            }
            return true;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("ERROR applying native CPU limit: " + ex.Message);
            return false;
        }
    }

    static int Main(string[] args)
    {
        if (args.Length == 4 && args[0] == "--Mode" && args[1] == "JobMemoryLimitChild")
            return MemoryProbeChild(args[2], ParseMemoryMiB(args[3]));
        MemoryJob memoryJob = null;
        int result = 99;
        try
        {
            bool probe = args.Length >= 4 && args[0] == "--Mode" && args[1] == "JobMemoryLimitProbe" && args[2] == "--MemoryLimitMiB";
            string cap = probe ? args[3] : Environment.GetEnvironmentVariable("RAS_COMMANDER_STORE_MAP_JOB_MEMORY_LIMIT_MIB");
            if (!String.IsNullOrEmpty(cap))
            {
                if (!probe && (Environment.GetEnvironmentVariable("RAS_COMMANDER_STORE_MAP_POLYGON_SERIAL") != "1" ||
                    args.Length < 6 || args[2] != "StoreMap" ||
                    (!String.Equals(args[3], "Depth", StringComparison.OrdinalIgnoreCase) && !String.Equals(args[3], "ProfileMap:depth", StringComparison.OrdinalIgnoreCase))))
                    throw new ArgumentException("Memory cap requires an individual serial Depth boundary");
                int mib = ParseMemoryMiB(cap);
                memoryJob = new MemoryJob(mib);
                if (probe) { result = RunMemoryProbe(args, memoryJob, mib); return result; }
                _jobMemoryLimited = true;
            }
            result = RunWithDiagnostics(args);
            return result;
        }
        catch (Exception error) { return HandleException(error); }
        finally
        {
            if (memoryJob != null)
            {
                try { memoryJob.Close(result == 0); }
                catch (Exception error)
                {
                    Console.Error.WriteLine("ERROR closing memory job: " + error.Message);
                    memoryJob.Close(false);
                }
            }
        }
    }

    static int RunWithDiagnostics(string[] args)
    {
        string diagnosticSetting = Environment.GetEnvironmentVariable("RAS_COMMANDER_STORE_MAP_DIAGNOSTICS");
        _diagnosticsEnabled = diagnosticSetting == "1" ||
            String.Equals(diagnosticSetting, "true", StringComparison.OrdinalIgnoreCase);
        if (_diagnosticsEnabled)
            AppDomain.CurrentDomain.FirstChanceException += OnFirstChanceException;
        try { return Run(args); }
        finally
        {
            if (_diagnosticsEnabled)
                AppDomain.CurrentDomain.FirstChanceException -= OnFirstChanceException;
        }
    }

    static int Run(string[] args)
    {
        if (args.Length < 3)
        {
            Console.Error.WriteLine("Usage:");
            Console.Error.WriteLine("  RasStoreMapHelper.exe <hecrasDir> <renderMode> <rasmapFile> [resultHdf]");
            Console.Error.WriteLine("  RasStoreMapHelper.exe <hecrasDir> <renderMode> StoreAllMaps <rasmapFile> [resultHdf]");
            Console.Error.WriteLine("  RasStoreMapHelper.exe <hecrasDir> <renderMode> StoreMap <mapType> <resultHdf> <profileName> [outputBasePath]");
            return 1;
        }

        if (!ConfigureNativeCpuLimit()) return 2;

        string polygonSetting = Environment.GetEnvironmentVariable("RAS_COMMANDER_STORE_MAP_POLYGON_SERIAL");
        if (!String.IsNullOrEmpty(polygonSetting) && polygonSetting != "0" && polygonSetting != "1")
        {
            Console.Error.WriteLine("ERROR: native_polygon_serial must be 0 or 1");
            return 2;
        }
        _polygonSerial = polygonSetting == "1";
        if (_polygonSerial && (args[2] != "StoreMap" || args.Length < 6 ||
            (!String.Equals(args[3], "Depth", StringComparison.OrdinalIgnoreCase) &&
             !String.Equals(args[3], "ProfileMap:depth", StringComparison.OrdinalIgnoreCase))))
        {
            Console.Error.WriteLine("ERROR: native_polygon_serial requires an individual Depth StoreMap");
            return 2;
        }
        string explicitTerrain = Environment.GetEnvironmentVariable("RAS_COMMANDER_STORE_MAP_TERRAIN_HDF");
        if (_polygonSerial && (String.IsNullOrEmpty(explicitTerrain) || !File.Exists(explicitTerrain)))
        {
            Console.Error.WriteLine("ERROR: native_polygon_serial requires an explicit existing terrain HDF");
            return 2;
        }

        _hecrasDir = args[0];
        string renderMode = args[1].ToLowerInvariant();

        // Register assembly resolver BEFORE any RasMapperLib types are used
        AppDomain.CurrentDomain.AssemblyResolve += ResolveAssembly;

        // Add HEC-RAS dir to PATH for native DLL resolution
        string envPath = Environment.GetEnvironmentVariable("PATH");
        Environment.SetEnvironmentVariable("PATH", _hecrasDir + ";" + envPath);

        if (!Directory.Exists(_hecrasDir))
        {
            Console.Error.WriteLine("ERROR: HEC-RAS directory not found: " + _hecrasDir);
            return 2;
        }

        // Load RasMapperLib
        string asmPath = Path.Combine(_hecrasDir, "RasMapperLib.dll");
        if (!File.Exists(asmPath))
        {
            Console.Error.WriteLine("ERROR: RasMapperLib.dll not found in " + _hecrasDir);
            return 2;
        }

        try
        {
            if (_jobMemoryLimited) ValidateMemoryRuntime();
            _asm = Assembly.LoadFrom(asmPath);
            if (_jobMemoryLimited &&
                (!String.Equals(Path.GetFullPath(_asm.Location), Path.GetFullPath(asmPath), StringComparison.OrdinalIgnoreCase) ||
                 MemoryRuntimeHash(_asm.Location) != MemoryRuntimeHash(asmPath)))
                throw new InvalidOperationException("Loaded mapper differs from admitted memory containment runtime");
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("ERROR loading RasMapperLib: " + ex.Message);
            return 2;
        }

        Console.WriteLine("HEC-RAS dir: " + _hecrasDir);
        Console.WriteLine("Render mode: " + renderMode);

        if (args[2] == "BoundaryPrimitives")
        {
            if (args.Length != 5)
            {
                Console.Error.WriteLine("ERROR: BoundaryPrimitives requires request XML and output directory");
                return 1;
            }
            return RunBoundaryPrimitives(args[3], args[4]);
        }

        // Set render mode
        int modeResult = SetRenderMode(renderMode);
        if (modeResult != 0)
            return modeResult;

        // Detect command mode
        string arg2 = args[2];

        if (arg2 == "StoreAllMaps")
        {
            // Explicit StoreAllMaps: args[3]=rasmap, args[4]=resultHdf
            if (args.Length < 4)
            {
                Console.Error.WriteLine("ERROR: StoreAllMaps requires rasmapFile argument");
                return 1;
            }
            return RunStoreAllMaps(args[3], args.Length > 4 ? args[4] : null);
        }
        else if (arg2 == "StoreMap")
        {
            // StoreMap: args[3]=mapType, args[4]=resultHdf, args[5]=profileName, args[6]=outputBase
            if (args.Length < 6)
            {
                Console.Error.WriteLine("ERROR: StoreMap requires mapType, resultHdf, profileName");
                return 1;
            }
            return RunStoreMap(args[3], args[4], args[5], args.Length > 6 ? args[6] : null);
        }
        else
        {
            // Legacy mode: arg2 is the rasmap file
            return RunStoreAllMaps(arg2, args.Length > 3 ? args[3] : null);
        }
    }

    // Render mode arguments: parsed from CLI as "sloping:true:false" or just "sloping"
    static bool _reduceShallow = false;
    static bool _depthWeighted = false;

    static int SetRenderMode(string renderMode)
    {
        Type sharedData = _asm.GetType("RasMapperLib.SharedData");
        if (sharedData == null)
        {
            Console.Error.WriteLine("ERROR: SharedData type not found in RasMapperLib");
            return 4;
        }

        // Parse render mode flags: "slopingPretty:true:false" or just "slopingPretty"
        string baseName = renderMode;
        if (renderMode.Contains(":"))
        {
            string[] parts = renderMode.Split(new char[] { ':' });
            baseName = parts[0];
            if (parts.Length > 1) _reduceShallow = parts[1].ToLower() == "true";
            if (parts.Length > 2) _depthWeighted = parts[2].ToLower() == "true";
        }

        bool modeSet = false;
        switch (baseName)
        {
            case "horizontal":
            {
                MethodInfo m = sharedData.GetMethod("SetHorizontalRenderingMode",
                    BindingFlags.Public | BindingFlags.Static);
                if (m != null) { m.Invoke(null, null); modeSet = true; }
                Console.WriteLine("RenderMode set: Horizontal");
                break;
            }
            case "sloping":
            {
                MethodInfo m = sharedData.GetMethod("SetSlopingRenderingMode",
                    BindingFlags.Public | BindingFlags.Static);
                if (m != null)
                {
                    // 6.0-6.1: no params. 6.2-6.3.1: (bool, bool). 6.5+: no params.
                    var parms = m.GetParameters();
                    if (parms.Length == 0)
                        m.Invoke(null, null);
                    else if (parms.Length == 2)
                        m.Invoke(null, new object[] { _reduceShallow, _depthWeighted });
                    else
                        m.Invoke(null, null); // best effort
                    modeSet = true;
                }
                // On 6.5+, SetSlopingRenderingMode() exists but SetSlopingPrettyRenderingMode
                // is the "pretty" variant. If user asked for "sloping" and the method takes
                // no params, this is correct plain sloping.
                Console.WriteLine("RenderMode set: Sloping (reduceShallow=" + _reduceShallow +
                    ", depthWeighted=" + _depthWeighted + ")");
                break;
            }
            case "slopingpretty":
            {
                // Default reduceShallow=true for slopingPretty (matches RASMapper GUI default)
                // unless explicitly overridden via "slopingpretty:false:false" syntax
                bool spReduceShallow = renderMode.Contains(":") ? _reduceShallow : true;
                bool spDepthWeighted = _depthWeighted; // false by default (causes no output if true)

                // Try SetSlopingPrettyRenderingMode (6.5+)
                MethodInfo m = sharedData.GetMethod("SetSlopingPrettyRenderingMode",
                    BindingFlags.Public | BindingFlags.Static);
                if (m != null)
                {
                    var parms = m.GetParameters();
                    if (parms.Length == 2)
                        m.Invoke(null, new object[] { spReduceShallow, spDepthWeighted });
                    else if (parms.Length == 0)
                        m.Invoke(null, null);
                    else
                        m.Invoke(null, null);
                    modeSet = true;
                    Console.WriteLine("RenderMode set: SlopingPretty (reduceShallow=" +
                        spReduceShallow + ", depthWeighted=" + spDepthWeighted + ")");
                }
                else
                {
                    // On 6.2-6.3.1, SlopingPretty doesn't exist.
                    // SetSlopingRenderingMode(bool, bool) is the equivalent.
                    m = sharedData.GetMethod("SetSlopingRenderingMode",
                        BindingFlags.Public | BindingFlags.Static);
                    if (m != null && m.GetParameters().Length == 2)
                    {
                        m.Invoke(null, new object[] { spReduceShallow, spDepthWeighted });
                        modeSet = true;
                        Console.WriteLine("RenderMode set: SlopingPretty via SetSlopingRenderingMode(bool,bool) [6.2-6.3.1]");
                    }
                    else
                    {
                        Console.Error.WriteLine("WARNING: SlopingPretty not available in this version.");
                    }
                }
                break;
            }
            default:
                Console.Error.WriteLine("ERROR: Unknown render mode: " + renderMode);
                Console.Error.WriteLine("  Valid: horizontal, sloping, slopingPretty");
                Console.Error.WriteLine("  Flags: sloping:reduceShallow:depthWeighted (e.g. slopingPretty:true:false)");
                return 3;
        }

        if (!modeSet)
            Console.Error.WriteLine("WARNING: Could not set render mode (method not found). Using default.");

        return 0;
    }

    static int RunStoreAllMaps(string rasmapFile, string resultFile)
    {
        if (!File.Exists(rasmapFile))
        {
            Console.Error.WriteLine("ERROR: rasmap file not found: " + rasmapFile);
            return 2;
        }

        Console.WriteLine("Rasmap file: " + rasmapFile);
        if (resultFile != null)
            Console.WriteLine("Result file: " + resultFile);

        try
        {
            Type cmdType = _asm.GetType("RasMapperLib.Scripting.StoreAllMapsCommand");
            if (cmdType == null)
            {
                Console.Error.WriteLine("ERROR: StoreAllMapsCommand not found");
                return 5;
            }

            object cmd;
            if (resultFile != null)
            {
                ConstructorInfo ctor = cmdType.GetConstructor(new Type[] { typeof(string), typeof(string) });
                if (ctor != null)
                    cmd = ctor.Invoke(new object[] { rasmapFile, resultFile });
                else
                {
                    cmd = Activator.CreateInstance(cmdType);
                    cmdType.GetProperty("RasMapFilename").SetValue(cmd, rasmapFile, null);
                    cmdType.GetProperty("ResultFilename").SetValue(cmd, resultFile, null);
                }
            }
            else
            {
                ConstructorInfo ctor = cmdType.GetConstructor(new Type[] { typeof(string) });
                if (ctor != null)
                    cmd = ctor.Invoke(new object[] { rasmapFile });
                else
                {
                    cmd = Activator.CreateInstance(cmdType);
                    cmdType.GetProperty("RasMapFilename").SetValue(cmd, rasmapFile, null);
                }
            }

            Console.WriteLine("Executing StoreAllMaps...");
            InvokeExecute(cmdType, cmd);
            Console.WriteLine("StoreAllMaps completed successfully.");
            return 0;
        }
        catch (TargetInvocationException tie)
        {
            return HandleException(tie.InnerException ?? tie);
        }
        catch (Exception ex)
        {
            return HandleException(ex);
        }
    }

    static int RunStoreMap(string mapType, string resultHdf, string profileName, string outputBasePath)
    {
        if (!File.Exists(resultHdf))
        {
            Console.Error.WriteLine("ERROR: result HDF not found: " + resultHdf);
            return 2;
        }

        Console.WriteLine("Map type:    " + mapType);
        Console.WriteLine("Result HDF:  " + resultHdf);
        Console.WriteLine("Profile:     " + profileName);
        if (outputBasePath != null)
            Console.WriteLine("Output base: " + outputBasePath);

        SeedProjectSrsFromResult(resultHdf);

        try
        {
            Type cmdType = _asm.GetType("RasMapperLib.Scripting.StoreMapCommand");
            if (cmdType == null)
            {
                Console.Error.WriteLine("ERROR: StoreMapCommand not found");
                return 5;
            }

            object cmd;

            if (mapType.StartsWith("ProfileMap:"))
            {
                // Generic ProfileMap factory: ProfileMap(resultFilename, MapTypes, pfName, outputBaseFilename)
                string xmlName = mapType.Substring(11); // after "ProfileMap:"

                // Load MapTypes instance via MapTypes.LoadFromXMLName(xmlName)
                Type mapTypesType = _asm.GetType("RasMapperLib.Mapping.MapTypes");
                if (mapTypesType == null)
                {
                    Console.Error.WriteLine("ERROR: MapTypes type not found");
                    return 5;
                }
                MethodInfo loadMethod = mapTypesType.GetMethod("LoadFromXMLName",
                    BindingFlags.Public | BindingFlags.Static);
                if (loadMethod == null)
                {
                    Console.Error.WriteLine("ERROR: MapTypes.LoadFromXMLName not found");
                    return 5;
                }
                object mapTypeInstance = loadMethod.Invoke(null, new object[] { xmlName });

                // Find ProfileMap factory
                MethodInfo factory = null;
                foreach (MethodInfo mi in cmdType.GetMethods(BindingFlags.Public | BindingFlags.Static))
                {
                    if (mi.Name == "ProfileMap")
                    {
                        factory = mi;
                        break;
                    }
                }
                if (factory == null)
                {
                    Console.Error.WriteLine("ERROR: StoreMapCommand.ProfileMap not found");
                    return 5;
                }

                // Call with appropriate args
                var factoryParams = factory.GetParameters();
                object[] factoryArgs = new object[factoryParams.Length];
                factoryArgs[0] = resultHdf;
                factoryArgs[1] = mapTypeInstance;
                factoryArgs[2] = profileName;
                if (factoryParams.Length > 3)
                    factoryArgs[3] = outputBasePath; // may be null (default)
                for (int i = 4; i < factoryParams.Length; i++)
                    factoryArgs[i] = factoryParams[i].DefaultValue;

                cmd = factory.Invoke(null, factoryArgs);
            }
            else
            {
                // Named factory: WSEL, Depth, Velocity, etc.
                MethodInfo factory = cmdType.GetMethod(mapType,
                    BindingFlags.Public | BindingFlags.Static);
                if (factory == null)
                {
                    Console.Error.WriteLine("ERROR: StoreMapCommand." + mapType + " not found");
                    Console.Error.WriteLine("  Valid: WSEL, Depth, Velocity, DepthTimesVelocity, DepthTimesVelocitySquared");
                    return 5;
                }

                // Factory signature: (string resultFilename, string pfName, string outputBaseFilename = ...)
                var factoryParams = factory.GetParameters();
                object[] factoryArgs = new object[factoryParams.Length];
                factoryArgs[0] = resultHdf;
                factoryArgs[1] = profileName;
                if (factoryParams.Length > 2)
                    factoryArgs[2] = outputBasePath; // may be null (uses default)
                for (int i = 3; i < factoryParams.Length; i++)
                    factoryArgs[i] = factoryParams[i].DefaultValue;

                cmd = factory.Invoke(null, factoryArgs);
            }

            if (cmd == null)
            {
                Console.Error.WriteLine("ERROR: Factory returned null");
                return 6;
            }

            if (_polygonSerial)
            {
                PropertyInfo terrainProperty = cmdType.GetProperty("Terrain");
                if (terrainProperty == null || !terrainProperty.CanWrite)
                    throw new Exception("StoreMapCommand.Terrain is unavailable");
                string terrainPath = Path.GetFullPath(Environment.GetEnvironmentVariable("RAS_COMMANDER_STORE_MAP_TERRAIN_HDF"));
                terrainProperty.SetValue(cmd, terrainPath, null);
                if (!String.Equals((string)terrainProperty.GetValue(cmd, null), terrainPath, StringComparison.Ordinal))
                    throw new Exception("StoreMapCommand.Terrain readback differs from request");
            }

            Console.WriteLine("Executing StoreMap...");
            string outputFile;
            bool success = ExecuteStoreMapHeadless(cmdType, cmd, out outputFile);

            Console.WriteLine("RESULT_SUCCESS=" + success);
            Console.WriteLine("RESULT_FILE=" + outputFile);

            if (success)
                Console.WriteLine("StoreMap completed successfully.");
            else
                Console.Error.WriteLine("StoreMap reported failure (ComputeSuccessful=False)");

            return success ? 0 : 7;
        }
        catch (TargetInvocationException tie)
        {
            return HandleException(tie.InnerException ?? tie);
        }
        catch (Exception ex)
        {
            return HandleException(ex);
        }
    }

    static void SeedProjectSrsFromResult(string resultHdf)
    {
        string rasmapFile = FindSiblingRasmap(resultHdf);
        if (rasmapFile == null)
        {
            Console.WriteLine("WARNING: Could not infer sibling rasmap for " + resultHdf);
            return;
        }

        try
        {
            XmlDocument doc = new XmlDocument();
            doc.Load(rasmapFile);

            XmlNode projectionNode =
                doc.SelectSingleNode("/RASMapper/RASProjectionFilename");
            string relativeSrsPath = null;
            if (
                projectionNode != null &&
                projectionNode.Attributes != null &&
                projectionNode.Attributes["Filename"] != null
            )
            {
                relativeSrsPath = projectionNode.Attributes["Filename"].Value;
            }
            if (string.IsNullOrEmpty(relativeSrsPath))
            {
                Console.WriteLine(
                    "WARNING: rasmap does not define RASProjectionFilename: "
                    + rasmapFile
                );
                return;
            }

            string srsPath = relativeSrsPath;
            if (!Path.IsPathRooted(srsPath))
            {
                srsPath = Path.GetFullPath(
                    Path.Combine(Path.GetDirectoryName(rasmapFile), srsPath)
                );
            }

            if (!File.Exists(srsPath))
            {
                Console.WriteLine(
                    "WARNING: Project SRS file not found: " + srsPath
                );
                return;
            }

            Type sharedData = _asm.GetType("RasMapperLib.SharedData");
            if (sharedData == null)
            {
                Console.WriteLine("WARNING: SharedData type not found");
                return;
            }

            PropertyInfo rasmapProp = sharedData.GetProperty(
                "RasMapFilename",
                BindingFlags.Public | BindingFlags.Static
            );
            if (rasmapProp != null)
                rasmapProp.SetValue(null, rasmapFile, null);

            PropertyInfo srsProp = sharedData.GetProperty(
                "SRSFilename",
                BindingFlags.Public | BindingFlags.Static
            );
            if (srsProp == null)
            {
                Console.WriteLine("WARNING: SharedData.SRSFilename not found");
                return;
            }

            srsProp.SetValue(null, srsPath, null);
            Console.WriteLine("Seeded project SRS from rasmap: " + srsPath);
        }
        catch (Exception ex)
        {
            Console.WriteLine(
                "WARNING: Could not seed project SRS from rasmap: "
                + ex.Message
            );
        }
    }

    static string FindSiblingRasmap(string resultHdf)
    {
        string directory = Path.GetDirectoryName(resultHdf);
        if (string.IsNullOrEmpty(directory) || !Directory.Exists(directory))
            return null;

        string filename = Path.GetFileName(resultHdf);
        string lowerFilename = filename.ToLowerInvariant();
        if (lowerFilename.EndsWith(".hdf"))
        {
            int planIndex = lowerFilename.LastIndexOf(".p");
            if (planIndex > 0)
            {
                string projectBase = filename.Substring(0, planIndex);
                string candidate =
                    Path.Combine(directory, projectBase + ".rasmap");
                if (File.Exists(candidate))
                    return candidate;
            }
        }

        string[] rasmaps = Directory.GetFiles(directory, "*.rasmap");
        if (rasmaps.Length == 1)
            return rasmaps[0];

        return null;
    }

    static bool ExecuteStoreMapHeadless(
        Type cmdType,
        object cmd,
        out string outputFile
    )
    {
        outputFile = "";

        string resultFilename = (string)cmdType
            .GetProperty("Result")
            .GetValue(cmd, null);
        object mapType = cmdType.GetProperty("MapType").GetValue(cmd, null);
        string outputBaseFilename = (string)cmdType
            .GetProperty("OutputBaseFilename")
            .GetValue(cmd, null);
        string terrainFilename = (string)cmdType
            .GetProperty("Terrain")
            .GetValue(cmd, null);
        string profileName = (string)cmdType
            .GetProperty("ProfileName")
            .GetValue(cmd, null);

        Type resultsType = _asm.GetType("RasMapperLib.RASResults");
        if (resultsType == null)
            throw new Exception("RASResults type not found");

        MethodInfo identifyResults = resultsType.GetMethod(
            "TryIdentifyResultsFile",
            BindingFlags.Public | BindingFlags.Static
        );
        if (identifyResults == null)
            throw new Exception("RASResults.TryIdentifyResultsFile not found");

        object results = identifyResults.Invoke(
            null,
            new object[] { resultFilename }
        );
        if (results == null)
            throw new Exception(
                "Result could not be identified '" + resultFilename + "'"
            );

        object geometry = resultsType
            .GetProperty("Geometry")
            .GetValue(results, null);
        if (geometry == null)
            throw new Exception("Results.Geometry is null");

        object terrainLayer;
        if (string.IsNullOrEmpty(terrainFilename))
        {
            terrainLayer = geometry.GetType()
                .GetProperty("Terrain")
                .GetValue(geometry, null);
        }
        else
        {
            Type terrainType = _asm.GetType("RasMapperLib.TerrainLayer");
            if (terrainType == null)
                throw new Exception("TerrainLayer type not found");

            terrainLayer = CreateTerrainLayer(terrainType, terrainFilename);

            MethodInfo setTerrainTemporary = geometry.GetType().GetMethod(
                "SetTerrainTemporary"
            );
            if (setTerrainTemporary == null)
                throw new Exception("SetTerrainTemporary method not found");
            setTerrainTemporary.Invoke(geometry, new object[] { terrainLayer });
        }

        if (terrainLayer == null)
            throw new Exception("Terrain is undefined or unavailable.");
        if (_polygonSerial)
        {
            PropertyInfo terrainSource = terrainLayer.GetType().GetProperty("SourceFilename");
            string actualTerrain = terrainSource == null ? null : terrainSource.GetValue(terrainLayer, null) as string;
            if (String.IsNullOrEmpty(actualTerrain) || !String.Equals(Path.GetFullPath(actualTerrain), Path.GetFullPath(terrainFilename), StringComparison.OrdinalIgnoreCase))
                throw new Exception("Native boundary terrain source differs from the explicit terrain HDF");
            terrainFilename = actualTerrain;
        }

        MethodInfo allSourceFilesExist = terrainLayer.GetType().GetMethod(
            "AllSourceFilesExist"
        );
        if (allSourceFilesExist == null)
            throw new Exception("TerrainLayer.AllSourceFilesExist not found");
        if (!(bool)allSourceFilesExist.Invoke(terrainLayer, null))
            throw new Exception(
                "Invalid terrain - required source files do not exist."
            );

        Type rasResultsMapType = _asm.GetType("RasMapperLib.RASResultsMap");
        if (rasResultsMapType == null)
            throw new Exception("RASResultsMap type not found");

        ConstructorInfo mapCtor = rasResultsMapType.GetConstructor(
            new Type[] { resultsType, mapType.GetType() }
        );
        if (mapCtor == null)
            throw new Exception(
                "RASResultsMap constructor for map type not found"
            );

        object resultsMap = mapCtor.Invoke(new object[] { results, mapType });

        PropertyInfo outputModeProp = rasResultsMapType.GetProperty("OutputMode");
        if (outputModeProp == null)
            throw new Exception("RASResultsMap.OutputMode property not found");

        string outputModeName = _polygonSerial ? "StoredPolygonSpecifiedDepth" : "StoredDefaultTerrain";
        object storedDefaultTerrain = GetStaticMemberValue(
            outputModeProp.PropertyType,
            outputModeName
        );
        if (storedDefaultTerrain == null)
            throw new Exception("OutputModes." + outputModeName + " not found");

        outputModeProp.SetValue(resultsMap, storedDefaultTerrain, null);
        if (_polygonSerial)
        {
            if (!Object.Equals(outputModeProp.GetValue(resultsMap, null), storedDefaultTerrain))
                throw new Exception("Native boundary output mode readback differs from request");
            ConfigurePolygonSerial(resultsMap, rasResultsMapType);
            Console.WriteLine("NATIVE_POLYGON_TERRAIN=" + Path.GetFullPath(terrainFilename));
            Console.WriteLine("NATIVE_POLYGON_OUTPUT_MODE=StoredPolygonSpecifiedDepth");
            Console.WriteLine("NATIVE_POLYGON_MAPPER_ASSEMBLY=" + _asm.Location);
            Console.WriteLine("NATIVE_POLYGON_MAPPER_VERSION=" + _asm.GetName().Version);
        }

        MethodInfo trySetProfile = rasResultsMapType.GetMethod("TrySetProfile");
        if (trySetProfile == null)
            throw new Exception("RASResultsMap.TrySetProfile not found");
        trySetProfile.Invoke(resultsMap, new object[] { profileName });
        if (_polygonSerial)
        {
            PropertyInfo profileIndex = rasResultsMapType.GetProperty("ProfileIndex");
            if (profileIndex == null || (int)profileIndex.GetValue(resultsMap, null) == -1)
                throw new Exception("Native boundary profile selection failed");
            Console.WriteLine("NATIVE_POLYGON_PROFILE_INDEX=" + profileIndex.GetValue(resultsMap, null));
        }

        if (!string.IsNullOrEmpty(outputBaseFilename))
        {
            PropertyInfo overwriteProp = rasResultsMapType.GetProperty(
                "OverwriteOutputFilename"
            );
            if (overwriteProp == null)
                throw new Exception(
                    "RASResultsMap.OverwriteOutputFilename not found"
                );
            overwriteProp.SetValue(resultsMap, outputBaseFilename, null);
        }

        Type setSrsHelperType = _asm.GetType("RasMapperLib.Scripting.SetSRSHelper");
        if (setSrsHelperType == null)
            throw new Exception("SetSRSHelper type not found");

        IDisposable srsHelper = CreateSrsHelper(setSrsHelperType, terrainLayer);
        try
        {
            MethodInfo storeMapMethod = FindStoreMapMethod(rasResultsMapType);
            if (storeMapMethod == null)
                throw new Exception(
                    "RASResultsMap.StoreMap(reporter, showFinishedMessage) "
                    + "not found"
                );

            bool success = (bool)storeMapMethod.Invoke(
                resultsMap,
                new object[] { null, false }
            );

            PropertyInfo vrtProp = rasResultsMapType.GetProperty(_polygonSerial ? "SHPFilename" : "VRTFilename");
            if (vrtProp != null)
                outputFile = (string)vrtProp.GetValue(resultsMap, null) ?? "";
            if (_polygonSerial && success)
            {
                if (String.IsNullOrEmpty(outputFile) || !String.Equals(Path.GetExtension(outputFile), ".shp", StringComparison.OrdinalIgnoreCase))
                    throw new Exception("Native boundary did not report a shapefile output");
                foreach (string extension in new string[] { ".shp", ".shx", ".dbf", ".prj" })
                {
                    if (!File.Exists(Path.ChangeExtension(outputFile, extension)))
                        throw new Exception("Native boundary output is missing " + extension);
                }
            }

            return success;
        }
        finally
        {
            if (srsHelper != null)
                srsHelper.Dispose();
        }
    }

    static int RunBoundaryPrimitives(string requestPath, string outputDirectory)
    {
        try
        {
            if (new FileInfo(requestPath).Length > 32 * 1024 * 1024)
                throw new Exception("Boundary primitive request exceeds 32 MiB");
            XmlReaderSettings settings = new XmlReaderSettings();
            settings.DtdProcessing = DtdProcessing.Prohibit;
            settings.XmlResolver = null;
            settings.MaxCharactersInDocument = 32 * 1024 * 1024;
            XmlDocument request = new XmlDocument();
            request.XmlResolver = null;
            using (XmlReader reader = XmlReader.Create(requestPath, settings)) request.Load(reader);
            XmlElement root = request.DocumentElement;
            if (root.Name != "boundary-primitives" || root.GetAttribute("schema") != "ras-commander-boundary-primitives/1")
                throw new Exception("Invalid boundary primitive request schema");
            if (!Directory.Exists(outputDirectory)) throw new Exception("Boundary primitive output directory is missing");
            string combined = Path.Combine(outputDirectory, "combined.xy");
            Type contourType = _asm.GetType("RasMapperLib.ContourBandRaster", true);
            MethodInfo merge = contourType.GetMethod("ExternalProcessMerge", BindingFlags.Static | BindingFlags.Public);
            if (merge == null) throw new Exception("Native ExternalProcessMerge is unavailable");
            XmlDocument report = new XmlDocument();
            XmlElement receipt = report.CreateElement("boundary-primitives-report");
            receipt.SetAttribute("schema", "ras-commander-boundary-primitives-report/1");
            receipt.SetAttribute("kind", root.GetAttribute("kind"));
            receipt.SetAttribute("appdomain_target_framework", AppDomain.CurrentDomain.SetupInformation.TargetFrameworkName ?? "unspecified");
            Type compatibility = typeof(object).Assembly.GetType("System.Runtime.Versioning.BinaryCompatibility");
            PropertyInfo targets45 = compatibility == null ? null : compatibility.GetProperty("TargetsAtLeast_Desktop_V4_5", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            receipt.SetAttribute("targets_at_least_desktop45", targets45 == null ? "unavailable" : Convert.ToString(targets45.GetValue(null, null), CultureInfo.InvariantCulture));
            receipt.SetAttribute("mapper_path", _asm.Location);
            receipt.SetAttribute("mapper_assembly_version", _asm.GetName().Version.ToString());
            using (SHA256 hash = SHA256.Create())
            using (FileStream assembly = File.OpenRead(_asm.Location))
                receipt.SetAttribute("mapper_sha256", BitConverter.ToString(hash.ComputeHash(assembly)).Replace("-", "").ToLowerInvariant());
            MethodInfo addNativePath = contourType.GetMethod("AddLongPointsToClipper", BindingFlags.Static | BindingFlags.NonPublic);
            if (addNativePath == null) throw new Exception("Native clipping backend parameter is unavailable");
            Assembly backend = addNativePath.GetParameters()[0].ParameterType.Assembly;
            receipt.SetAttribute("clipper_path", backend.Location);
            receipt.SetAttribute("clipper_assembly_version", backend.GetName().Version.ToString());
            using (SHA256 hash = SHA256.Create())
            using (FileStream assembly = File.OpenRead(backend.Location))
                receipt.SetAttribute("clipper_sha256", BitConverter.ToString(hash.ComputeHash(assembly)).Replace("-", "").ToLowerInvariant());
            report.AppendChild(receipt);
            XmlElement units = report.CreateElement("units");
            receipt.AppendChild(units);
            string kind = root.GetAttribute("kind");
            int maxRings = 10000;
            bool explicitRingLimit = root.HasAttribute("max_rings");
            if (explicitRingLimit)
            {
                if (kind != "rings" || !Int32.TryParse(root.GetAttribute("max_rings"), NumberStyles.None,
                    CultureInfo.InvariantCulture, out maxRings) || maxRings < 1 || maxRings > 50000)
                    throw new Exception("Primitive max_rings must be an integer from 1 through 50000 for rings");
                receipt.SetAttribute("max_rings_effective", maxRings.ToString(CultureInfo.InvariantCulture));
                receipt.SetAttribute("max_report_vertices_effective", "500000");
                Console.WriteLine("BOUNDARY_PRIMITIVE_MAX_RINGS_EFFECTIVE=" + maxRings.ToString(CultureInfo.InvariantCulture));
            }
            if (kind == "terrain_rfi")
            {
                WriteTerrainRfi(root, report, receipt);
            }
            else if (kind == "rings")
            {
                XmlNodeList rings = root.SelectNodes("ring");
                if (rings.Count > maxRings) throw new Exception("Boundary primitive ring count exceeds " + maxRings.ToString(CultureInfo.InvariantCulture));
                int total = 0;
                using (BinaryWriter writer = new BinaryWriter(File.Open(combined, FileMode.CreateNew)))
                {
                    foreach (XmlNode ring in rings)
                    {
                        XmlNodeList points = ring.SelectNodes("p");
                        total = checked(total + points.Count);
                        if (points.Count < 3 || total > 500000) throw new Exception("Invalid boundary primitive vertex count");
                        writer.Write(points.Count);
                        foreach (XmlNode point in points)
                        {
                            long x = Int64.Parse(point.Attributes["x"].Value, CultureInfo.InvariantCulture);
                            long y = Int64.Parse(point.Attributes["y"].Value, CultureInfo.InvariantCulture);
                            if (Math.Abs((double)x) > (1L << 50) || Math.Abs((double)y) > (1L << 50)) throw new Exception("Primitive coordinate exceeds range");
                            writer.Write(x); writer.Write(y);
                        }
                    }
                }
                AddPrimitiveRings(report, units, combined, "0", explicitRingLimit ? 500000 : 131072);
            }
            else if (kind == "grids")
            {
                XmlNodeList grids = root.SelectNodes("grid");
                if (grids.Count < 1 || grids.Count > 4) throw new Exception("Boundary primitive grid count must be 1 through 4");
                Type rasterType = _asm.GetType("RasMapperLib.RasterM", true);
                MethodInfo contourRaster = contourType.GetMethod("ContourRaster", new Type[] { rasterType, typeof(float[]) });
                MethodInfo close = contourType.GetMethod("CloseBinaryWriters", BindingFlags.Instance | BindingFlags.NonPublic);
                FieldInfo filenames = contourType.GetField("_bandXYFilename", BindingFlags.Instance | BindingFlags.NonPublic);
                if (contourRaster == null || close == null || filenames == null) throw new Exception("Native primitive contour members are unavailable");
                using (FileStream destination = File.Open(combined, FileMode.CreateNew))
                {
                    for (int index = 0; index < grids.Count; index++)
                    {
                        XmlElement grid = (XmlElement)grids[index];
                        int rows = Int32.Parse(grid.GetAttribute("rows"), CultureInfo.InvariantCulture);
                        int cols = Int32.Parse(grid.GetAttribute("cols"), CultureInfo.InvariantCulture);
                        if (rows < 2 || cols < 2 || rows > 33 || cols > 33) throw new Exception("Primitive grid must be 2 through 33 rows/columns");
                        double left = PrimitiveDouble(grid, "left"), top = PrimitiveDouble(grid, "top");
                        double dx = PrimitiveDouble(grid, "dx"), dy = PrimitiveDouble(grid, "dy");
                        if (dx <= 0 || dy >= 0) throw new Exception("Primitive grid must be north-up");
                        XmlNodeList samples = grid.SelectNodes("v");
                        if (samples.Count != rows * cols) throw new Exception("Primitive grid sample count differs");
                        float[] values = new float[samples.Count];
                        for (int n = 0; n < values.Length; n++)
                        {
                            uint bits = UInt32.Parse(samples[n].Attributes["bits"].Value, NumberStyles.HexNumber, CultureInfo.InvariantCulture);
                            values[n] = BitConverter.ToSingle(BitConverter.GetBytes(bits), 0);
                            if (Single.IsNaN(values[n]) || Single.IsInfinity(values[n])) throw new Exception("Nonfinite primitive sample");
                        }
                        object raster = Activator.CreateInstance(rasterType, new object[] { rows, cols, left + cols * dx, left, top, top + rows * dy });
                        object contour = Activator.CreateInstance(contourType, new object[] { Path.Combine(outputDirectory, "unit-" + index + ".shp"), 0f, Single.MaxValue });
                        try { contourRaster.Invoke(contour, new object[] { raster, values }); }
                        finally { close.Invoke(contour, null); }
                        string nativeFile = ((string[])filenames.GetValue(contour))[0];
                        string retained = Path.Combine(outputDirectory, "unit-" + index.ToString("D4") + ".xy");
                        File.Copy(nativeFile, retained, false);
                        using (FileStream unit = File.OpenRead(retained)) unit.CopyTo(destination);
                        AddPrimitiveRings(report, units, retained, index.ToString(CultureInfo.InvariantCulture));
                    }
                }
            }
            else throw new Exception("Unknown boundary primitive kind");
            if (kind != "terrain_rfi")
            {
                merge.Invoke(null, new object[] { combined });
                XmlElement final = report.CreateElement("final");
                receipt.AppendChild(final);
                AddPrimitiveRings(report, final, combined + ".out", "0", explicitRingLimit ? 500000 : 131072);
            }
            receipt.SetAttribute("status", "completed");
            string reportPath = Path.Combine(outputDirectory, "primitive-report.xml");
            report.Save(reportPath);
            Console.WriteLine("RESULT_SUCCESS=True");
            Console.WriteLine("RESULT_FILE=" + reportPath);
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine("ERROR: boundary primitive: " + exception);
            return 99;
        }
    }

    static object PrimitiveMember(object target, string name)
    {
        Type type = target.GetType();
        FieldInfo field = type.GetField(name);
        return field != null ? field.GetValue(target) : type.GetProperty(name).GetValue(target, null);
    }

    static void PrimitiveRaster(XmlDocument report, XmlElement parent, string name, object raster)
    {
        XmlElement node = report.CreateElement(name); parent.AppendChild(node);
        foreach (string key in new string[] { "Rows", "Cols", "MinX", "MaxX", "MinY", "MaxY", "CellSize" })
        {
            object value = PrimitiveMember(raster, key);
            node.SetAttribute(key, Convert.ToString(value, CultureInfo.InvariantCulture));
            if (value is double) node.SetAttribute(key + "_bits", BitConverter.DoubleToInt64Bits((double)value).ToString("X16"));
        }
    }

    // Read existing HDF/TIFF only; deliberately bypass TerrainLayer's VRT creation.
    static void WriteTerrainRfi(XmlElement request, XmlDocument report, XmlElement receipt)
    {
        if (SetRenderMode("horizontal") != 0) throw new Exception("Native RFI GDAL initialization failed");
        string hdf = Path.GetFullPath(request.GetAttribute("terrain_hdf_path"));
        string tiff = Path.GetFullPath(request.GetAttribute("terrain_tiff_path"));
        if (!File.Exists(hdf) || !File.Exists(tiff)) throw new Exception("RFI source files must exist");
        XmlNodeList tiles = request.SelectNodes("tile");
        if (tiles.Count < 1 || tiles.Count > 8) throw new Exception("RFI tile count must be one through eight");
        Type rfiType = _asm.GetType("RasMapperLib.Terrain.RasterFileInfo", true);
        ConstructorInfo[] rfiConstructors = rfiType.GetConstructors();
        if (rfiConstructors.Length != 1) throw new Exception("RFI constructor contract differs");
        ConstructorInfo constructor = rfiConstructors[0];
        Type readerType = constructor.GetParameters()[0].ParameterType;
        object reader = null;
        foreach (ConstructorInfo candidate in readerType.GetConstructors())
        {
            ParameterInfo[] parameters = candidate.GetParameters();
            if (parameters.Length == 0 || parameters[0].ParameterType != typeof(string)) continue;
            object[] args = new object[parameters.Length]; args[0] = hdf; bool admitted = true;
            for (int i = 1; i < args.Length; i++) { admitted &= parameters[i].IsOptional; args[i] = parameters[i].DefaultValue; }
            if (admitted) { reader = candidate.Invoke(args); break; }
        }
        if (reader == null) throw new Exception("Read-only H5Reader filename constructor unavailable");
        try
        {
            object groups = readerType.InvokeMember("GetGroupNames", BindingFlags.Public | BindingFlags.Instance | BindingFlags.InvokeMethod | BindingFlags.OptionalParamBinding,
                null, reader, new object[] { "Terrain" }, CultureInfo.InvariantCulture);
            object selected = null;
            foreach (object group in (System.Collections.IEnumerable)groups)
            {
                object rfi = constructor.Invoke(new object[] { reader, Path.GetDirectoryName(hdf), Path.GetFileNameWithoutExtension(hdf), group.ToString() });
                if (String.Equals(Path.GetFullPath((string)PrimitiveMember(rfi, "Filename")), tiff, StringComparison.OrdinalIgnoreCase))
                { if (selected != null) throw new Exception("Duplicate RFI source"); selected = rfi; }
            }
            if (selected == null) throw new Exception("Explicit TIFF is absent from terrain HDF");
            receipt.SetAttribute("terrain_hdf_path", hdf); receipt.SetAttribute("terrain_tiff_path", tiff);
            PrimitiveRaster(report, receipt, "rfi_extent", Activator.CreateInstance(_asm.GetType("RasMapperLib.RasterM", true),
                new object[] { (int)PrimitiveMember(selected, "Rows"), (int)PrimitiveMember(selected, "Cols"), PrimitiveMember(PrimitiveMember(selected,"Extent"),"MaxX"),
                    PrimitiveMember(PrimitiveMember(selected,"Extent"),"MinX"), PrimitiveMember(PrimitiveMember(selected,"Extent"),"MaxY"), PrimitiveMember(PrimitiveMember(selected,"Extent"),"MinY") }));
            object coarse = ((Array)PrimitiveMember(selected, "TileRasters")).GetValue(0);
            int tileSize = (int)((Array)PrimitiveMember(selected, "TileSize")).GetValue(0);
            PrimitiveRaster(report, receipt, "tile_index_raster", coarse);
            foreach (XmlElement tile in tiles)
            {
                int index = Int32.Parse(tile.GetAttribute("id"), CultureInfo.InvariantCulture);
                if (index < 0 || index >= checked((int)PrimitiveMember(coarse,"Rows") * (int)PrimitiveMember(coarse,"Cols"))) throw new Exception("RFI tile ID out of range");
                XmlElement node = report.CreateElement("tile"); node.SetAttribute("id", index.ToString(CultureInfo.InvariantCulture)); receipt.AppendChild(node);
                object raster = coarse.GetType().GetMethod("GetCellRasterM").Invoke(coarse, new object[] { index, tileSize });
                PrimitiveRaster(report, node, "source", raster);
                PrimitiveRaster(report, node, "extended", raster.GetType().GetMethod("ExtendRaster").Invoke(raster, new object[] { 0, 1, 0, 1 }));
            }
        }
        finally { ((IDisposable)reader).Dispose(); }
        foreach (System.Diagnostics.ProcessModule module in System.Diagnostics.Process.GetCurrentProcess().Modules)
        {
            if (!module.FileName.StartsWith(_hecrasDir + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                && module.ModuleName.IndexOf("gdal", StringComparison.OrdinalIgnoreCase) < 0) continue;
            XmlElement node = report.CreateElement("loaded_module"); node.SetAttribute("path", module.FileName);
            using (SHA256 hash = SHA256.Create()) using (FileStream file = File.OpenRead(module.FileName))
                node.SetAttribute("sha256", BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "").ToLowerInvariant());
            receipt.AppendChild(node);
        }
    }

    static double PrimitiveDouble(XmlElement node, string name)
    {
        double value = Double.Parse(node.GetAttribute(name), CultureInfo.InvariantCulture);
        if (Double.IsNaN(value) || Double.IsInfinity(value) || Math.Abs(value) > (1L << 40))
            throw new Exception("Invalid primitive grid coordinate/step");
        return value;
    }

    static void AddPrimitiveRings(XmlDocument report, XmlElement parent, string path, string sequence, int maxVertices = 131072)
    {
        XmlElement unit = report.CreateElement("unit");
        unit.SetAttribute("sequence", sequence);
        unit.SetAttribute("binary", Path.GetFileName(path));
        parent.AppendChild(unit);
        using (BinaryReader reader = new BinaryReader(File.OpenRead(path)))
        {
            if (reader.BaseStream.Length > 8 * 1024 * 1024) throw new Exception("Primitive native output exceeds 8 MiB");
            int total = 0;
            while (reader.BaseStream.Position < reader.BaseStream.Length)
            {
                int count = reader.ReadInt32();
                total = checked(total + count);
                if (count < 0 || total > maxVertices) throw new Exception("Invalid primitive native output vertex count");
                XmlElement ring = report.CreateElement("ring");
                unit.AppendChild(ring);
                for (int n = 0; n < count; n++)
                {
                    XmlElement point = report.CreateElement("p");
                    point.SetAttribute("x", reader.ReadInt64().ToString(CultureInfo.InvariantCulture));
                    point.SetAttribute("y", reader.ReadInt64().ToString(CultureInfo.InvariantCulture));
                    ring.AppendChild(point);
                }
            }
        }
    }

    static object CreateTerrainLayer(Type terrainType, string terrainFilename)
    {
        ConstructorInfo constructor = terrainType.GetConstructor(new Type[] { typeof(string), typeof(string) });
        if (constructor != null)
            return constructor.Invoke(new object[] { "Terrain", terrainFilename });
        // C# optional arguments are real CLR parameters. The 6.6 and 7.0.1
        // runtimes expose (name, filename, canEdit=true), not a two-arg overload.
        constructor = terrainType.GetConstructor(new Type[] { typeof(string), typeof(string), typeof(bool) });
        if (constructor != null && constructor.GetParameters()[2].IsOptional)
            return constructor.Invoke(new object[] { "Terrain", terrainFilename, constructor.GetParameters()[2].DefaultValue });
        throw new Exception("TerrainLayer(name, filename[, optional canEdit]) constructor not found");
    }

    // This controls the actual ParallelOptions on polygon tiles. Affinity is
    // independent and does not establish a single contour writer.
    static void ConfigurePolygonSerial(object resultsMap, Type mapType)
    {
        PropertyInfo contour = mapType.GetProperty("ContourPolygonValue");
        if (contour == null || !contour.CanWrite || contour.PropertyType != typeof(float))
            throw new Exception("RASResultsMap.ContourPolygonValue is unavailable");
        FieldInfo serial = mapType.GetField("FORCE_POLYGON_SERIAL", BindingFlags.Instance | BindingFlags.NonPublic);
        if (serial == null || serial.FieldType != typeof(bool))
            throw new Exception("RASResultsMap.FORCE_POLYGON_SERIAL is unavailable");
        contour.SetValue(resultsMap, 0f, null);
        serial.SetValue(resultsMap, true);
        if ((float)contour.GetValue(resultsMap, null) != 0f || !(bool)serial.GetValue(resultsMap))
            throw new Exception("Native polygon serial control readback failed");
        Console.WriteLine("NATIVE_POLYGON_SERIAL_EFFECTIVE=True");
        Console.WriteLine("NATIVE_POLYGON_CONTOUR=0");
    }

    static IDisposable CreateSrsHelper(Type setSrsHelperType, object terrainLayer)
    {
        ConstructorInfo ctor = setSrsHelperType.GetConstructor(
            new Type[] { terrainLayer.GetType(), typeof(bool) }
        );
        if (ctor != null)
            return (IDisposable)ctor.Invoke(
                new object[] { terrainLayer, false }
            );

        ctor = setSrsHelperType.GetConstructor(
            new Type[] { terrainLayer.GetType() }
        );
        if (ctor != null)
            return (IDisposable)ctor.Invoke(new object[] { terrainLayer });

        throw new Exception("Suitable SetSRSHelper constructor not found");
    }

    static MethodInfo FindStoreMapMethod(Type rasResultsMapType)
    {
        foreach (
            MethodInfo method in rasResultsMapType.GetMethods(
                BindingFlags.Public | BindingFlags.Instance
            )
        )
        {
            if (method.Name != "StoreMap")
                continue;

            ParameterInfo[] parameters = method.GetParameters();
            if (
                parameters.Length == 2 &&
                parameters[1].ParameterType == typeof(bool)
            )
            {
                return method;
            }
        }

        return null;
    }

    static object GetStaticMemberValue(Type type, string name)
    {
        FieldInfo field = type.GetField(
            name,
            BindingFlags.Public | BindingFlags.Static
        );
        if (field != null)
            return field.GetValue(null);

        PropertyInfo property = type.GetProperty(
            name,
            BindingFlags.Public | BindingFlags.Static
        );
        if (property != null)
            return property.GetValue(null, null);

        return null;
    }

    static void InvokeExecute(Type cmdType, object cmd)
    {
        MethodInfo executeMethod = cmdType.GetMethod("Execute");
        if (executeMethod == null)
        {
            // Try base class
            executeMethod = cmdType.BaseType.GetMethod("Execute");
        }
        if (executeMethod == null)
            throw new Exception("Execute method not found on " + cmdType.Name);

        var parameters = executeMethod.GetParameters();
        if (parameters.Length == 0)
        {
            executeMethod.Invoke(cmd, null);
        }
        else
        {
            object[] execArgs = new object[parameters.Length];
            for (int i = 0; i < parameters.Length; i++)
                execArgs[i] = parameters[i].DefaultValue;

            // Native commands can report fatal errors and return normally. Passing
            // null installs a silent reporter, so a successful Invoke is not enough.
            Type reporterType = parameters[0].ParameterType;
            EventInfo messageEvent = reporterType.GetEvent("MessageReported");
            if (messageEvent == null)
                throw new NotSupportedException("Native command progress reporter has no MessageReported event");
            object reporter = Activator.CreateInstance(reporterType);
            ParameterInfo[] messageParameters = messageEvent.EventHandlerType.GetMethod("Invoke").GetParameters();
            ParameterExpression message = Expression.Parameter(messageParameters[0].ParameterType, "message");
            ParameterExpression kind = Expression.Parameter(messageParameters[1].ParameterType, "kind");
            MethodInfo callback = typeof(RasStoreMapHelper).GetMethod("OnNativeMessage", BindingFlags.Static | BindingFlags.NonPublic);
            Delegate handler = Expression.Lambda(messageEvent.EventHandlerType,
                Expression.Call(callback, message, Expression.Convert(kind, typeof(object))), message, kind).Compile();
            Interlocked.Exchange(ref _reportedErrors, 0);
            messageEvent.AddEventHandler(reporter, handler);
            execArgs[0] = reporter;
            try
            {
                executeMethod.Invoke(cmd, execArgs);
            }
            finally
            {
                messageEvent.RemoveEventHandler(reporter, handler);
            }
            if (_reportedErrors != 0)
                throw new Exception("Native stored-map command reported " + _reportedErrors + " error(s)");
        }
    }

    static int _reportedErrors;

    static void OnNativeMessage(string message, object kind)
    {
        string label = kind.ToString();
        if (label == "Debug") WriteDiagnostic("DEBUG", message);
        if (label.IndexOf("Error", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            Interlocked.Increment(ref _reportedErrors);
            Console.Error.WriteLine("NATIVE_" + label + ": " + message);
        }
        else if (label != "ProgressUpdate" && label != "Debug")
            Console.WriteLine("NATIVE_" + label + ": " + message);
    }

    static int HandleException(Exception ex)
    {
        Console.Error.WriteLine("ERROR: " + ex.GetType().Name + ": " + ex.Message);
        if (ex.InnerException != null)
            Console.Error.WriteLine("INNER: " + ex.InnerException.GetType().Name +
                ": " + ex.InnerException.Message);
        Console.Error.WriteLine(ex.StackTrace);
        return 99;
    }
}
