using System;
using System.IO;
using System.Reflection;

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
            Console.Error.WriteLine("Usage:");
            Console.Error.WriteLine("  RasStoreMapHelper.exe <hecrasDir> <renderMode> <rasmapFile> [resultHdf]");
            Console.Error.WriteLine("  RasStoreMapHelper.exe <hecrasDir> <renderMode> StoreAllMaps <rasmapFile> [resultHdf]");
            Console.Error.WriteLine("  RasStoreMapHelper.exe <hecrasDir> <renderMode> StoreMap <mapType> <resultHdf> <profileName> [outputBasePath]");
            return 1;
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
            _asm = Assembly.LoadFrom(asmPath);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("ERROR loading RasMapperLib: " + ex.Message);
            return 2;
        }

        Console.WriteLine("HEC-RAS dir: " + _hecrasDir);
        Console.WriteLine("Render mode: " + renderMode);

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

    static int SetRenderMode(string renderMode)
    {
        Type sharedData = _asm.GetType("RasMapperLib.SharedData");
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
                if (m != null) { m.Invoke(null, null); modeSet = true; }
                Console.WriteLine("RenderMode set: Horizontal");
                break;
            }
            case "sloping":
            {
                MethodInfo m = sharedData.GetMethod("SetSlopingRenderingMode",
                    BindingFlags.Public | BindingFlags.Static);
                if (m != null) { m.Invoke(null, null); modeSet = true; }
                Console.WriteLine("RenderMode set: Sloping");
                break;
            }
            case "slopingpretty":
            {
                MethodInfo m = sharedData.GetMethod("SetSlopingPrettyRenderingMode",
                    BindingFlags.Public | BindingFlags.Static);
                if (m != null) { m.Invoke(null, new object[] { false, false }); modeSet = true; }
                Console.WriteLine("RenderMode set: SlopingPretty");
                break;
            }
            default:
                Console.Error.WriteLine("ERROR: Unknown render mode: " + renderMode);
                Console.Error.WriteLine("  Valid: horizontal, sloping, slopingPretty");
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

            Console.WriteLine("Executing StoreMap...");
            InvokeExecute(cmdType, cmd);

            // Read results
            PropertyInfo successProp = cmdType.GetProperty("ComputeSuccessful");
            PropertyInfo outputProp = cmdType.GetProperty("ActualOutputFilename");

            bool success = true;
            string outputFile = "";

            if (successProp != null)
                success = (bool)successProp.GetValue(cmd, null);
            if (outputProp != null)
                outputFile = (string)outputProp.GetValue(cmd, null) ?? "";

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
            executeMethod.Invoke(cmd, execArgs);
        }
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
