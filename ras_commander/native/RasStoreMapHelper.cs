using System;
using System.IO;
using System.Reflection;
using System.Xml;

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

            ConstructorInfo terrainCtor = terrainType.GetConstructor(
                new Type[] { typeof(string), typeof(string) }
            );
            if (terrainCtor == null)
                throw new Exception(
                    "TerrainLayer(string, string) constructor not found"
                );

            terrainLayer = terrainCtor.Invoke(
                new object[] { "Terrain", terrainFilename }
            );

            MethodInfo setTerrainTemporary = geometry.GetType().GetMethod(
                "SetTerrainTemporary"
            );
            if (setTerrainTemporary == null)
                throw new Exception("SetTerrainTemporary method not found");
            setTerrainTemporary.Invoke(geometry, new object[] { terrainLayer });
        }

        if (terrainLayer == null)
            throw new Exception("Terrain is undefined or unavailable.");

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

        object storedDefaultTerrain = GetStaticMemberValue(
            outputModeProp.PropertyType,
            "StoredDefaultTerrain"
        );
        if (storedDefaultTerrain == null)
            throw new Exception("OutputModes.StoredDefaultTerrain not found");

        outputModeProp.SetValue(resultsMap, storedDefaultTerrain, null);

        MethodInfo trySetProfile = rasResultsMapType.GetMethod("TrySetProfile");
        if (trySetProfile == null)
            throw new Exception("RASResultsMap.TrySetProfile not found");
        trySetProfile.Invoke(resultsMap, new object[] { profileName });

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

            PropertyInfo vrtProp = rasResultsMapType.GetProperty("VRTFilename");
            if (vrtProp != null)
                outputFile = (string)vrtProp.GetValue(resultsMap, null) ?? "";

            return success;
        }
        finally
        {
            if (srsHelper != null)
                srsHelper.Dispose();
        }
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
