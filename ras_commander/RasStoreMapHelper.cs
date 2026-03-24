using System;
using System.IO;
using System.Reflection;

/// <summary>
/// Headless stored map generator that respects rendering mode.
/// Designed to replace RasProcess.exe StoreAllMaps which ignores RenderMode in 6.x.
///
/// Uses reflection for SharedData render mode calls to work across HEC-RAS versions
/// (6.3.1, 6.5, 6.6, etc.) without recompilation.
///
/// Usage: RasStoreMapHelper.exe hecrasDir renderMode rasmapFile [resultHdfFile]
/// </summary>
class RasStoreMapHelper
{
    static string _hecrasDir;

    static Assembly ResolveAssembly(object sender, ResolveEventArgs e)
    {
        string name = new AssemblyName(e.Name).Name;
        string path = Path.Combine(_hecrasDir, name + ".dll");
        if (File.Exists(path))
            return Assembly.LoadFrom(path);
        return null;
    }

    static int Main(string[] args)
    {
        if (args.Length < 3)
        {
            Console.Error.WriteLine("Usage: RasStoreMapHelper.exe <hecrasDir> <renderMode> <rasmapFile> [resultHdfFile]");
            Console.Error.WriteLine("  renderMode: horizontal | sloping | slopingPretty");
            return 1;
        }

        _hecrasDir = args[0];
        string renderMode = args[1].ToLowerInvariant();
        string rasmapFile = args[2];
        string resultFile = args.Length > 3 ? args[3] : null;

        // Register assembly resolver BEFORE any RasMapperLib types are used
        AppDomain.CurrentDomain.AssemblyResolve += ResolveAssembly;

        // Add HEC-RAS dir to PATH for native DLL resolution
        string path = Environment.GetEnvironmentVariable("PATH");
        Environment.SetEnvironmentVariable("PATH", _hecrasDir + ";" + path);

        if (!Directory.Exists(_hecrasDir))
        {
            Console.Error.WriteLine("ERROR: HEC-RAS directory not found: " + _hecrasDir);
            return 2;
        }
        if (!File.Exists(rasmapFile))
        {
            Console.Error.WriteLine("ERROR: rasmap file not found: " + rasmapFile);
            return 2;
        }

        Console.WriteLine("HEC-RAS dir: " + _hecrasDir);
        Console.WriteLine("Render mode: " + renderMode);
        Console.WriteLine("Rasmap file: " + rasmapFile);
        if (resultFile != null)
            Console.WriteLine("Result file: " + resultFile);

        try
        {
            // Load RasMapperLib via reflection (version-independent)
            Assembly asm = Assembly.LoadFrom(Path.Combine(_hecrasDir, "RasMapperLib.dll"));

            // --- Set render mode via reflection ---
            Type sharedData = asm.GetType("RasMapperLib.SharedData");
            if (sharedData == null)
            {
                Console.Error.WriteLine("ERROR: SharedData type not found in RasMapperLib");
                return 4;
            }

            bool modeSet = false;
            switch (renderMode)
            {
                case "horizontal":
                {
                    MethodInfo m = sharedData.GetMethod("SetHorizontalRenderingMode",
                        BindingFlags.Public | BindingFlags.Static);
                    if (m != null)
                    {
                        m.Invoke(null, null);
                        modeSet = true;
                        Console.WriteLine("RenderMode set: Horizontal");
                    }
                    break;
                }
                case "sloping":
                {
                    MethodInfo m = sharedData.GetMethod("SetSlopingRenderingMode",
                        BindingFlags.Public | BindingFlags.Static);
                    if (m != null)
                    {
                        m.Invoke(null, null);
                        modeSet = true;
                        Console.WriteLine("RenderMode set: Sloping");
                    }
                    break;
                }
                case "slopingpretty":
                {
                    MethodInfo m = sharedData.GetMethod("SetSlopingPrettyRenderingMode",
                        BindingFlags.Public | BindingFlags.Static);
                    if (m != null)
                    {
                        m.Invoke(null, new object[] { false, false });
                        modeSet = true;
                        Console.WriteLine("RenderMode set: SlopingPretty");
                    }
                    break;
                }
                default:
                    Console.Error.WriteLine("ERROR: Unknown render mode: " + renderMode);
                    Console.Error.WriteLine("  Valid: horizontal, sloping, slopingPretty");
                    return 3;
            }

            if (!modeSet)
            {
                Console.Error.WriteLine("WARNING: Could not set render mode '" + renderMode +
                    "' (method not found in this HEC-RAS version). Proceeding with default.");
            }

            // --- Create and execute StoreAllMapsCommand via reflection ---
            Type cmdType = asm.GetType("RasMapperLib.Scripting.StoreAllMapsCommand");
            if (cmdType == null)
            {
                Console.Error.WriteLine("ERROR: StoreAllMapsCommand not found in RasMapperLib");
                return 5;
            }

            object cmd;
            if (resultFile != null)
            {
                ConstructorInfo ctor = cmdType.GetConstructor(new Type[] {
                    typeof(string), typeof(string) });
                if (ctor != null)
                {
                    cmd = ctor.Invoke(new object[] { rasmapFile, resultFile });
                }
                else
                {
                    // Fallback: parameterless constructor + set properties
                    cmd = Activator.CreateInstance(cmdType);
                    cmdType.GetProperty("RasMapFilename").SetValue(cmd, rasmapFile, null);
                    cmdType.GetProperty("ResultFilename").SetValue(cmd, resultFile, null);
                }
            }
            else
            {
                ConstructorInfo ctor = cmdType.GetConstructor(new Type[] { typeof(string) });
                if (ctor != null)
                {
                    cmd = ctor.Invoke(new object[] { rasmapFile });
                }
                else
                {
                    cmd = Activator.CreateInstance(cmdType);
                    cmdType.GetProperty("RasMapFilename").SetValue(cmd, rasmapFile, null);
                }
            }

            Console.WriteLine("Executing StoreAllMaps...");

            // Call Execute(ProgressReporter prog = null)
            MethodInfo executeMethod = cmdType.GetMethod("Execute");
            if (executeMethod != null)
            {
                // Handle optional parameter
                var parameters = executeMethod.GetParameters();
                if (parameters.Length == 0)
                {
                    executeMethod.Invoke(cmd, null);
                }
                else
                {
                    // Pass null for optional ProgressReporter
                    object[] execArgs = new object[parameters.Length];
                    for (int i = 0; i < parameters.Length; i++)
                        execArgs[i] = parameters[i].DefaultValue;
                    executeMethod.Invoke(cmd, execArgs);
                }
            }
            else
            {
                Console.Error.WriteLine("ERROR: Execute method not found on StoreAllMapsCommand");
                return 6;
            }

            Console.WriteLine("StoreAllMaps completed successfully.");
            return 0;
        }
        catch (TargetInvocationException tie)
        {
            Exception inner = tie.InnerException ?? tie;
            Console.Error.WriteLine("ERROR: " + inner.GetType().Name + ": " + inner.Message);
            if (inner.InnerException != null)
                Console.Error.WriteLine("INNER: " + inner.InnerException.GetType().Name +
                    ": " + inner.InnerException.Message);
            Console.Error.WriteLine(inner.StackTrace);
            return 99;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("ERROR: " + ex.GetType().Name + ": " + ex.Message);
            if (ex.InnerException != null)
                Console.Error.WriteLine("INNER: " + ex.InnerException.GetType().Name +
                    ": " + ex.InnerException.Message);
            Console.Error.WriteLine(ex.StackTrace);
            return 99;
        }
    }
}
