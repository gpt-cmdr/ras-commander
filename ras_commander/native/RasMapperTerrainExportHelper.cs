using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Web.Script.Serialization;
using System.Xml;

internal static class RasMapperTerrainExportHelper
{
    private const int SchemaVersion = 1;
    private static string _hecRasDirectory;
    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

    public static int Main(string[] args)
    {
        string responsePath = args.Length >= 3 ? args[2] : null;
        var response = NewResponse();

        try
        {
            if (args.Length != 3)
                throw new ArgumentException(
                    "Usage: RasMapperTerrainExportHelper.exe <hecras-dir> <request.json> <response.json>");

            _hecRasDirectory = Path.GetFullPath(args[0]);
            AppDomain.CurrentDomain.AssemblyResolve += ResolveAssembly;
            response = Run(Path.GetFullPath(args[1]));
            WriteResponse(responsePath, response);
            return Convert.ToBoolean(response["success"], CultureInfo.InvariantCulture) ? 0 : 1;
        }
        catch (Exception error)
        {
            error = Unwrap(error);
            response["success"] = false;
            response["error_type"] = error.GetType().FullName;
            response["error"] = error.Message;
            response["details"] = error.ToString();
            try
            {
                WriteResponse(responsePath, response);
            }
            catch (Exception responseError)
            {
                Console.Error.WriteLine(responseError.ToString());
            }
            Console.Error.WriteLine(error.ToString());
            return 1;
        }
    }

    private static Dictionary<string, object> Run(string requestPath)
    {
        var request = Json.Deserialize<Dictionary<string, object>>(
            File.ReadAllText(requestPath));
        RequireInteger(request, "schema_version", SchemaVersion);
        string operation = RequireString(request, "operation");
        if (operation != "inspect" && operation != "export")
            throw new ArgumentException("operation must be 'inspect' or 'export'");

        string rasmapPath = Path.GetFullPath(RequireString(request, "rasmap_path"));
        string terrainName = RequireString(request, "terrain_name");
        if (!File.Exists(rasmapPath))
            throw new FileNotFoundException("RAS Mapper file not found", rasmapPath);

        XmlDocument document = new XmlDocument();
        document.Load(rasmapPath);
        RasMapperLib.SharedData.RasMapFilename = rasmapPath;
        RasMapperLib.SharedData.SRSFilename =
            RasMapperLib.RASMapperCom.GetSRSFromRasmapDoc(document, rasmapPath);
        XmlNode unitsNode = document.SelectSingleNode("/RASMapper/Units");
        if (unitsNode != null && !String.IsNullOrWhiteSpace(unitsNode.InnerText))
            RasMapperLib.SharedData.SetUnitsSystem(unitsNode.InnerText.Trim());

        XmlElement selected = null;
        foreach (XmlElement element in document.SelectNodes("/RASMapper/Terrains/Layer"))
        {
            if (String.Equals(
                element.GetAttribute("Name"), terrainName, StringComparison.Ordinal))
            {
                selected = element;
                break;
            }
        }
        if (selected == null)
            throw new InvalidOperationException(
                "Registered terrain was not found by exact name: " + terrainName);

        var terrain = new RasMapperLib.TerrainLayer(terrainName);
        terrain.XMLLoad(selected);

        var response = NewResponse();
        response["success"] = true;
        response["operation"] = operation;
        response["terrain_name"] = terrainName;
        response["terrain_extent"] = ExtentDictionary(terrain.Extent);
        response["sources"] = SourceInventory(terrain);
        response["rasmapper_assembly_version"] =
            typeof(RasMapperLib.TerrainLayer).Assembly.GetName().Version.ToString();

        if (operation == "inspect")
            return response;

        string outputPath = Path.GetFullPath(RequireString(request, "output_path"));
        if (File.Exists(outputPath))
            throw new IOException("The helper output already exists: " + outputPath);

        double[] bounds = RequireDoubleArray(request, "invocation_extent", 4);
        double cellSize = RequireDouble(request, "cell_size");
        if (!(cellSize > 0.0) || Double.IsInfinity(cellSize) || Double.IsNaN(cellSize))
            throw new ArgumentException("cell_size must be finite and positive");
        bool modifications = RequireBoolean(request, "rasterize_modifications");

        terrain.ResampleMethod = "near";
        var requestedExtent = new RasMapperLib.Extent(
            bounds[2], bounds[0], bounds[3], bounds[1]);
        var progressValues = new List<int>();
        var messages = new List<Dictionary<string, object>>();
        var progress = new Utility.Progress.ProgressReporter();
        progress.ProgressReported += value => progressValues.Add(value);
        progress.MessageReported += (message, type) => messages.Add(
            new Dictionary<string, object> {
                { "type", type.ToString() },
                { "message", message ?? "" }
            });
        Action<RasMapperLib.SpatialIndex<int>> callback =
            index => index.Add(requestedExtent, 0);
        var newFiles = new List<string>();

        MethodInfo method = ResolveGenerateMethod();
        object[] invokeArguments = {
            outputPath,
            requestedExtent,
            cellSize,
            true,
            modifications,
            progress,
            callback,
            newFiles,
            null
        };
        method.Invoke(terrain, invokeArguments);

        response["generate_method"] = method.ToString();
        response["generate_method_is_public"] = method.IsPublic;
        response["resample_method"] = terrain.ResampleMethod;
        response["resample_to_one_rfi"] = true;
        response["rasterize_modifications"] = modifications;
        response["new_rfis"] = newFiles.ToArray();
        response["progress"] = progressValues.ToArray();
        response["messages"] = messages.ToArray();
        response["metadata_returned"] = invokeArguments[8] != null;
        response["output_path"] = outputPath;
        response["output_exists"] = File.Exists(outputPath);
        response["output_size_bytes"] = File.Exists(outputPath)
            ? new FileInfo(outputPath).Length
            : 0L;

        if (!File.Exists(outputPath))
            throw new InvalidOperationException("Native export returned without an output TIFF");
        if (newFiles.Count != 1 || !SamePath(newFiles[0], outputPath))
            throw new InvalidOperationException(
                "Native export did not report exactly the requested single TIFF");

        return response;
    }

    private static MethodInfo ResolveGenerateMethod()
    {
        MethodInfo[] candidates = typeof(RasMapperLib.TerrainLayer)
            .GetMethods(BindingFlags.Instance | BindingFlags.NonPublic)
            .Where(candidate => candidate.Name == "GenerateNewRasTerrain")
            .Where(candidate => candidate.GetParameters().Length == 9)
            .ToArray();
        if (candidates.Length != 1)
            throw new MissingMethodException(
                "Expected one private TerrainLayer.GenerateNewRasTerrain overload with nine parameters; found " +
                candidates.Length.ToString(CultureInfo.InvariantCulture));

        ParameterInfo[] parameters = candidates[0].GetParameters();
        string[] expected = {
            "System.String",
            "RasMapperLib.Extent",
            "System.Double",
            "System.Boolean",
            "System.Boolean",
            "Utility.Progress.ProgressReporter",
            "System.Action`1[[RasMapperLib.SpatialIndex`1[[System.Int32",
            "System.Collections.Generic.List`1[[System.String",
            "TiffAssist.TiffMetadata`1[[System.Single"
        };
        for (int index = 0; index < expected.Length; index++)
        {
            string actual = parameters[index].ParameterType.FullName;
            if (actual == null || !actual.StartsWith(expected[index], StringComparison.Ordinal))
                throw new MissingMethodException(
                    "GenerateNewRasTerrain parameter " + index +
                    " changed from the verified contract: " + actual);
        }
        if (!parameters[8].ParameterType.IsByRef)
            throw new MissingMethodException(
                "GenerateNewRasTerrain metadata parameter is no longer by-reference");
        return candidates[0];
    }

    private static List<Dictionary<string, object>> SourceInventory(
        RasMapperLib.TerrainLayer terrain)
    {
        var sources = new List<Dictionary<string, object>>();
        for (int index = 0; index < terrain.RasterFileCount; index++)
        {
            var info = terrain.RasterFileInfo(index);
            var record = new Dictionary<string, object>();
            record["index"] = index;
            record["filename"] = info.Filename;
            record["priority"] = info.Priority;
            record["columns"] = info.Cols;
            record["rows"] = info.Rows;
            record["extent"] = ExtentDictionary(info.Extent);
            record["cell_sizes"] = info.CellSize == null
                ? new double[0]
                : info.CellSize.ToArray();
            record["levels"] = info.Levels;
            sources.Add(record);
        }
        return sources;
    }

    private static Dictionary<string, object> ExtentDictionary(
        RasMapperLib.Extent extent)
    {
        return new Dictionary<string, object> {
            { "min_x", extent.MinX },
            { "min_y", extent.MinY },
            { "max_x", extent.MaxX },
            { "max_y", extent.MaxY }
        };
    }

    private static Dictionary<string, object> NewResponse()
    {
        return new Dictionary<string, object> {
            { "schema_version", SchemaVersion },
            { "helper", "RasMapperTerrainExportHelper" },
            { "success", false }
        };
    }

    private static Assembly ResolveAssembly(object sender, ResolveEventArgs args)
    {
        string filename = new AssemblyName(args.Name).Name + ".dll";
        string candidate = Path.Combine(_hecRasDirectory, filename);
        return File.Exists(candidate) ? Assembly.LoadFrom(candidate) : null;
    }

    private static void WriteResponse(string path, Dictionary<string, object> response)
    {
        if (String.IsNullOrWhiteSpace(path))
            throw new ArgumentException("A response path is required");
        File.WriteAllText(Path.GetFullPath(path), Json.Serialize(response));
    }

    private static Exception Unwrap(Exception error)
    {
        while (error is TargetInvocationException && error.InnerException != null)
            error = error.InnerException;
        return error;
    }

    private static string RequireString(Dictionary<string, object> values, string key)
    {
        object value;
        if (!values.TryGetValue(key, out value) || value == null ||
            String.IsNullOrWhiteSpace(Convert.ToString(value, CultureInfo.InvariantCulture)))
            throw new ArgumentException("Missing non-empty request field: " + key);
        return Convert.ToString(value, CultureInfo.InvariantCulture);
    }

    private static void RequireInteger(
        Dictionary<string, object> values, string key, int expected)
    {
        object value;
        if (!values.TryGetValue(key, out value) ||
            Convert.ToInt32(value, CultureInfo.InvariantCulture) != expected)
            throw new ArgumentException(
                key + " must equal " + expected.ToString(CultureInfo.InvariantCulture));
    }

    private static double RequireDouble(Dictionary<string, object> values, string key)
    {
        object value;
        if (!values.TryGetValue(key, out value))
            throw new ArgumentException("Missing numeric request field: " + key);
        return Convert.ToDouble(value, CultureInfo.InvariantCulture);
    }

    private static bool RequireBoolean(Dictionary<string, object> values, string key)
    {
        object value;
        if (!values.TryGetValue(key, out value))
            throw new ArgumentException("Missing boolean request field: " + key);
        return Convert.ToBoolean(value, CultureInfo.InvariantCulture);
    }

    private static double[] RequireDoubleArray(
        Dictionary<string, object> values, string key, int count)
    {
        object value;
        if (!values.TryGetValue(key, out value))
            throw new ArgumentException("Missing array request field: " + key);
        var items = value as System.Collections.IEnumerable;
        if (items == null)
            throw new ArgumentException(
                key + " must contain exactly " + count + " numbers");
        var converted = new List<double>();
        foreach (object item in items)
            converted.Add(Convert.ToDouble(item, CultureInfo.InvariantCulture));
        if (converted.Count != count)
            throw new ArgumentException(
                key + " must contain exactly " + count + " numbers");
        return converted.ToArray();
    }

    private static bool SamePath(string left, string right)
    {
        return String.Equals(
            Path.GetFullPath(left).TrimEnd(Path.DirectorySeparatorChar),
            Path.GetFullPath(right).TrimEnd(Path.DirectorySeparatorChar),
            StringComparison.OrdinalIgnoreCase);
    }
}
