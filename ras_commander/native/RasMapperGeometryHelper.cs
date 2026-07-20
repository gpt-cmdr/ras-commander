using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

/// <summary>
/// Out-of-process host for RasMapperLib geometry-association and property-table
/// commands. Keeping these calls in a bounded x86 CLR process prevents a Wine
/// CLR access violation or non-returning vendor call from corrupting the Python
/// qualification worker.
/// </summary>
internal static class RasMapperGeometryHelper
{
    private static string _hecrasDir = "";
    private static string _progressPath = "";
    private static Assembly _assembly;
    private static readonly Stopwatch Timer = Stopwatch.StartNew();

    private static Assembly ResolveAssembly(object sender, ResolveEventArgs args)
    {
        string name = new AssemblyName(args.Name).Name;
        string path = Path.Combine(_hecrasDir, name + ".dll");
        return File.Exists(path) ? Assembly.LoadFrom(path) : null;
    }

    private static object Property(object instance, string name)
    {
        PropertyInfo property = instance.GetType().GetProperty(name);
        if (property == null)
            throw new MissingMemberException(instance.GetType().FullName, name);
        return property.GetValue(instance, null);
    }

    private static void SetProperty(object instance, string name, string value)
    {
        if (String.IsNullOrEmpty(value))
            return;
        PropertyInfo property = instance.GetType().GetProperty(name);
        if (property == null)
            throw new MissingMemberException(instance.GetType().FullName, name);
        property.SetValue(instance, value, null);
    }

    private static void Stage(string value)
    {
        Console.Error.WriteLine("geometry-host-stage: " + value);
        Console.Error.Flush();
        if (!String.IsNullOrEmpty(_progressPath))
            File.AppendAllText(
                _progressPath,
                Timer.Elapsed.TotalSeconds.ToString(
                    "0.000000",
                    CultureInfo.InvariantCulture
                ) + " " + value + Environment.NewLine,
                new UTF8Encoding(false)
            );
    }

    private static string JsonEscape(string value)
    {
        if (value == null)
            return "";
        StringBuilder escaped = new StringBuilder();
        foreach (char character in value)
        {
            switch (character)
            {
                case '\\': escaped.Append("\\\\"); break;
                case '"': escaped.Append("\\\""); break;
                case '\r': escaped.Append("\\r"); break;
                case '\n': escaped.Append("\\n"); break;
                case '\t': escaped.Append("\\t"); break;
                default:
                    if (character < 0x20)
                        escaped.Append("\\u" + ((int)character).ToString("x4"));
                    else
                        escaped.Append(character);
                    break;
            }
        }
        return escaped.ToString();
    }

    private static void WriteReceipt(
        string path,
        string action,
        string status,
        string geometryHdf,
        string meshName,
        bool commandReturned,
        string error
    )
    {
        string json = "{" +
            "\"backend\":\"managed_host\"," +
            "\"action\":\"" + JsonEscape(action) + "\"," +
            "\"status\":\"" + JsonEscape(status) + "\"," +
            "\"geometry_hdf\":\"" + JsonEscape(geometryHdf) + "\"," +
            "\"mesh_name\":\"" + JsonEscape(meshName) + "\"," +
            "\"command_returned\":" + (commandReturned ? "true" : "false") + "," +
            "\"duration_seconds\":" +
                Timer.Elapsed.TotalSeconds.ToString("0.000000", CultureInfo.InvariantCulture) + "," +
            "\"error\":\"" + JsonEscape(error) + "\"" +
            "}";
        File.WriteAllText(path, json, new UTF8Encoding(false));
    }

    private static Exception Unwrap(Exception exception)
    {
        Exception current = exception;
        while (current is TargetInvocationException && current.InnerException != null)
            current = current.InnerException;
        return current;
    }

    private static void ConfigureRuntime()
    {
        string applicationGdal = Path.Combine(
            AppDomain.CurrentDomain.BaseDirectory,
            "GDAL"
        );
        if (
            !Directory.Exists(Path.Combine(applicationGdal, "bin64")) ||
            !Directory.Exists(Path.Combine(applicationGdal, "common", "data"))
        )
            throw new DirectoryNotFoundException(
                "RasMapperLib requires a usable GDAL directory next to " +
                "RasMapperGeometryHelper.exe: " + applicationGdal
            );

        AppDomain.CurrentDomain.AssemblyResolve += ResolveAssembly;
        string gdalData = Path.Combine(applicationGdal, "common", "data");
        Environment.SetEnvironmentVariable(
            "PATH",
            _hecrasDir + ";" + Path.Combine(applicationGdal, "bin64") +
            ";" + Environment.GetEnvironmentVariable("PATH")
        );
        Environment.SetEnvironmentVariable("GDAL_DATA", gdalData);
        Environment.SetEnvironmentVariable("PROJ_LIB", gdalData);
        Environment.SetEnvironmentVariable("PROJ_DATA", gdalData);
        _assembly = Assembly.LoadFrom(Path.Combine(_hecrasDir, "RasMapperLib.dll"));
        Stage("runtime-loaded");
    }

    private static bool Associate(string[] args)
    {
        if (args.Length != 8)
            throw new ArgumentException(
                "associate requires TERRAIN LANDCOVER INFILTRATION SEDIMENT paths"
            );
        Type commandType = _assembly.GetType(
            "RasMapperLib.Scripting.SetGeometryAssociationCommand",
            true
        );
        object command = Activator.CreateInstance(commandType);
        SetProperty(command, "GeometryFilename", args[2]);
        SetProperty(command, "TerrainFilename", args[4]);
        SetProperty(command, "NValueFilename", args[5]);
        SetProperty(command, "InfiltrationFilename", args[6]);
        SetProperty(command, "SedimentSoilsFilename", args[7]);
        MethodInfo execute = commandType.GetMethods().Single(method =>
            method.Name == "Execute" && method.GetParameters().Length == 1
        );
        execute.Invoke(command, new object[] { null });
        Stage("association-command-returned");
        return true;
    }

    private static bool ComputePropertyTables(string[] args)
    {
        if (args.Length != 8)
            throw new ArgumentException(
                "property-tables requires MESH_NAME, FORCE, RASMAP, and " +
                "RUN_COMPLETE arguments"
            );
        string meshName = args[4];
        bool force = Boolean.Parse(args[5]);
        string rasmapPath = args[6];
        bool runComplete = Boolean.Parse(args[7]);
        Type geometryType = _assembly.GetType("RasMapperLib.RASGeometry", true);
        object geometry = Activator.CreateInstance(
            geometryType,
            new object[] { args[2] }
        );
        Stage("geometry-opened");
        object d2FlowArea = Property(geometry, "D2FlowArea");
        MethodInfo getFeatureByName = d2FlowArea.GetType().GetMethods().Single(method =>
            method.Name == "GetFeatureByName" &&
            method.GetParameters().Length == 1 &&
            method.GetParameters()[0].ParameterType == typeof(string)
        );
        int fid = Convert.ToInt32(
            getFeatureByName.Invoke(d2FlowArea, new object[] { meshName })
        );
        if (fid < 0)
            throw new ArgumentException(
                "2D flow area not found in RASGeometry: " + meshName
            );
        if (Property(geometry, "Terrain") == null)
            throw new InvalidOperationException(
                "No terrain associated with geometry: " + args[2]
            );

        if (force)
        {
            if (runComplete)
            {
                Type completeType = _assembly.GetType(
                    "RasMapperLib.Scripting.CompleteGeometryCommand",
                    true
                );
                object completeCommand = Activator.CreateInstance(completeType);
                SetProperty(completeCommand, "GeometryFilename", args[2]);
                SetProperty(completeCommand, "RasmapFilename", rasmapPath);
                MethodInfo completeExecute = completeType.GetMethods().Single(candidate =>
                    candidate.Name == "Execute" &&
                    candidate.GetParameters().Length == 1
                );
                completeExecute.Invoke(completeCommand, new object[] { null });
                Stage("complete-geometry-command-returned");
            }
            else
            {
                Stage("complete-geometry-command-skipped");
            }

            Type computeType = _assembly.GetType(
                "RasMapperLib.Scripting.ComputePropertyTablesCommand",
                true
            );
            object computeCommand = Activator.CreateInstance(computeType);
            SetProperty(computeCommand, "Geometry", args[2]);
            MethodInfo computeExecute = computeType.GetMethods().Single(candidate =>
                candidate.Name == "Execute" && candidate.GetParameters().Length == 1
            );
            computeExecute.Invoke(computeCommand, new object[] { null });
            Stage("property-tables-command-returned");
            return true;
        }

        MethodInfo ensureMethod = d2FlowArea.GetType().GetMethods().Single(candidate =>
            candidate.Name == "EnsurePropertyTables" &&
            candidate.GetParameters().Length == 4
        );
        object result = ensureMethod.Invoke(
                d2FlowArea,
                new object[] { false, true, false, null }
            );
        bool returned = Convert.ToBoolean(result, CultureInfo.InvariantCulture);
        Stage("property-tables-command-returned");
        return returned;
    }

    public static int Main(string[] args)
    {
        if (args.Length < 4)
        {
            Console.Error.WriteLine(
                "Usage: RasMapperGeometryHelper.exe ACTION HECRAS_DIR " +
                "GEOMETRY_HDF RECEIPT_JSON [ACTION_ARGS]"
            );
            return 2;
        }

        string action = args[0];
        _hecrasDir = args[1];
        string geometryHdf = args[2];
        string receiptPath = args[3];
        string meshName = action == "property-tables" && args.Length > 4
            ? args[4]
            : "";
        _progressPath = receiptPath + ".progress";
        if (File.Exists(_progressPath))
            File.Delete(_progressPath);
        bool commandReturned = false;

        try
        {
            ConfigureRuntime();
            if (action == "associate")
                commandReturned = Associate(args);
            else if (action == "property-tables")
                commandReturned = ComputePropertyTables(args);
            else
                throw new ArgumentException("Unsupported action: " + action);

            WriteReceipt(
                receiptPath,
                action,
                commandReturned ? "complete" : "error",
                geometryHdf,
                meshName,
                commandReturned,
                commandReturned ? "" : "RasMapperLib command returned false"
            );
            return commandReturned ? 0 : 98;
        }
        catch (Exception exception)
        {
            Exception error = Unwrap(exception);
            string detail = error.GetType().FullName + ": " + error.Message;
            try
            {
                WriteReceipt(
                    receiptPath,
                    action,
                    "error",
                    geometryHdf,
                    meshName,
                    commandReturned,
                    detail
                );
            }
            catch
            {
                // Preserve the original exception as the process diagnostic.
            }
            Console.Error.WriteLine(detail);
            Console.Error.WriteLine(error.StackTrace);
            return 99;
        }
    }
}
