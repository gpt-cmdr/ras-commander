using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Linq.Expressions;
using System.Reflection;
using System.Text;

/// <summary>
/// Out-of-process RasMapperLib mesh host for Wine/.NET Framework.
///
/// Python.NET can corrupt its reflected type cache or become non-returning
/// while RasMapperLib generates points under Wine.  This host keeps those
/// calls entirely inside a small x86 CLR process and writes a JSON receipt for
/// ras-commander to validate before accepting the mesh.
/// </summary>
internal static class RasMapperMeshHelper
{
    private sealed class RefinementRegionReceipt
    {
        public int Fid;
        public string Name;
        public double SpacingDx;
        public double SpacingDy;
        public int PointCount;
    }

    private sealed class PersistenceReceipt
    {
        public string Mode = "skip";
        public bool ReloadSuppressorCreated;
        public bool ReloadSuppressorDisposed;
        public bool ReloadSuppressorDisposedBeforeReopen;
        public string ReloadSuppressorType = "";
        public bool SetFeatureReturnedDataRow;
        public bool SetFeatureRowReferenceMatchesGenerated;
        public string SetFeatureColumnName = "";
        public bool FeatureTableWritten;
        public bool FeatureTableTargetValidated;
        public bool MeshPointsSetFeatureReturnedDataRow;
        public bool MeshPointsSetFeatureRowReferenceMatchesGenerated;
        public bool MeshPointsFeatureTableWritten;
        public bool FeatureTableRestoredAfterMeshPoints;
        public bool CellCountSerializerOverrideRegistered;
        public bool CellCountSerializerFirstVerified;
        public bool FeatureTableContainsCellCountColumn;
        public bool LayerMeshReferenceMatchesGenerated;
        public bool LayerMeshComplete;
        public int LayerMeshCellCount;
        public int LayerMeshFaceCount;
        public int VendorManagedCellCountBeforeOverride;
        public int FeatureTableTargetFid = -1;
        public int FeatureTableTargetCellCount;
        public int SaveMeshParameterCount;
        public bool SaveMeshForce;
        public bool WriterFlushAttempted;
        public bool WriterFlushSucceeded;
        public string WriterFlushError = "";
        public string SeedGenerationMethod = "regenerate";
        public bool SeedFallbackUsed;
        public double SeedFallbackCellSize;
        public string RegenerateParameterSignature = "";
        public bool ReopenedTopologyValidated;
        public int ReopenedCellCount;
        public int ReopenedFaceCount;
        public bool ReopenedCentersValidated;
        public double ReopenedCenterMaxAbsError = -1.0;
        public int MeshIterations;
        public List<string> FixesApplied = new List<string>();
    }

    private sealed class ReloadSuppressorHandle : IDisposable
    {
        private IDisposable _inner;

        public bool IsDisposed { get; private set; }

        public ReloadSuppressorHandle(IDisposable inner)
        {
            if (inner == null)
                throw new ArgumentNullException("inner");
            _inner = inner;
        }

        public void Dispose()
        {
            if (IsDisposed)
                return;
            _inner.Dispose();
            _inner = null;
            IsDisposed = true;
        }
    }

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

    private static List<int> FeatureIds(object layer)
    {
        if (layer == null)
            return new List<int>();
        MethodInfo featureCount = layer.GetType().GetMethods()
            .Single(method =>
                method.Name == "FeatureCount" &&
                method.GetParameters().Length == 0
            );
        int count = Convert.ToInt32(featureCount.Invoke(layer, null));
        return Enumerable.Range(0, count).ToList();
    }

    private static object InvokeFeatureMethod(
        object layer,
        string methodName,
        int fid
    )
    {
        MethodInfo method = layer.GetType().GetMethods()
            .Single(candidate =>
                candidate.Name == methodName &&
                candidate.GetParameters().Length == 1 &&
                candidate.GetParameters()[0].ParameterType == typeof(int)
            );
        return method.Invoke(layer, new object[] { fid });
    }

    private static object RowValue(object row, string column)
    {
        return row.GetType().GetProperty("Item", new[] { typeof(string) })
            .GetValue(row, new object[] { column });
    }

    private static List<RefinementRegionReceipt> RefinementRegions(
        object layer
    )
    {
        List<RefinementRegionReceipt> result =
            new List<RefinementRegionReceipt>();
        foreach (int fid in FeatureIds(layer))
        {
            object row = InvokeFeatureMethod(layer, "FeatureRow", fid);
            object polygon = InvokeFeatureMethod(layer, "Polygon", fid);
            MethodInfo getFeatureName = layer.GetType().GetMethods()
                .Single(method =>
                    method.Name == "GetFeatureName" &&
                    method.GetParameters().Length == 1 &&
                    method.GetParameters()[0].ParameterType == typeof(int)
                );
            result.Add(new RefinementRegionReceipt {
                Fid = fid,
                Name = Convert.ToString(
                    getFeatureName.Invoke(layer, new object[] { fid }),
                    CultureInfo.InvariantCulture
                ),
                SpacingDx = Convert.ToDouble(
                    RowValue(row, "Cell Size X"),
                    CultureInfo.InvariantCulture
                ),
                SpacingDy = Convert.ToDouble(
                    RowValue(row, "Cell Size Y"),
                    CultureInfo.InvariantCulture
                ),
                PointCount = polygon == null
                    ? 0
                    : Convert.ToInt32(Property(polygon, "Count"))
            });
        }
        return result;
    }

    private static void SetRowValue(object row, string column, object value)
    {
        row.GetType().GetProperty("Item", new[] { typeof(string) })
            .SetValue(row, value, new object[] { column });
    }

    private static int AddPolylineFeatures(
        object sourceLayer,
        string enumerateMethod,
        object destinationLayer,
        Type polylineType
    )
    {
        if (sourceLayer == null)
            return 0;
        MethodInfo enumerate = sourceLayer.GetType().GetMethod(enumerateMethod);
        if (enumerate == null)
            return 0;
        MethodInfo isValid = polylineType.GetMethod(
            "IsValidPolyline",
            BindingFlags.Public | BindingFlags.Static,
            null,
            new[] { polylineType },
            null
        );
        int added = 0;
        foreach (object feature in (IEnumerable)enumerate.Invoke(sourceLayer, null))
        {
            if (!(bool)isValid.Invoke(null, new object[] { feature }))
                continue;
            MethodInfo addFeature = destinationLayer.GetType().GetMethods()
                .Where(method =>
                    method.Name == "AddFeature" &&
                    method.GetParameters().Length == 1 &&
                    method.GetParameters()[0].ParameterType.IsAssignableFrom(
                        feature.GetType()
                    )
                )
                .OrderBy(method =>
                    method.GetParameters()[0].ParameterType == feature.GetType()
                        ? 0
                        : 1
                )
                .First();
            addFeature.Invoke(destinationLayer, new object[] { feature });
            added++;
        }
        return added;
    }

    private static int PointCount(object points)
    {
        PropertyInfo count = points.GetType().GetProperty("Count");
        if (count != null)
            return Convert.ToInt32(count.GetValue(points, null));
        MethodInfo pointMCount = points.GetType().GetMethod(
            "PointMCount",
            Type.EmptyTypes
        );
        if (pointMCount != null)
            return Convert.ToInt32(pointMCount.Invoke(points, null));
        throw new MissingMemberException(
            points.GetType().FullName,
            "Count/PointMCount"
        );
    }

    private static object PointAt(object points, int index)
    {
        MethodInfo pointM = points.GetType().GetMethod(
            "PointM",
            new[] { typeof(int) }
        );
        if (pointM != null)
            return pointM.Invoke(points, new object[] { index });
        PropertyInfo item = points.GetType().GetProperty("Item");
        if (item != null)
            return item.GetValue(points, new object[] { index });
        throw new MissingMemberException(
            points.GetType().FullName,
            "PointM/Item"
        );
    }

    private static object AddMaxFaceMidpointSeeds(
        object mesh,
        object seeds,
        out int added
    )
    {
        Type pointMType = _assembly.GetType("RasMapperLib.PointM", true);
        Type pointMsType = _assembly.GetType("RasMapperLib.PointMs", true);
        object augmented = Activator.CreateInstance(pointMsType);
        MethodInfo addPoint = pointMsType.GetMethods()
            .First(method =>
                method.Name == "Add" &&
                method.GetParameters().Length == 1 &&
                method.GetParameters()[0].ParameterType.IsAssignableFrom(
                    pointMType
                )
            );
        for (int index = 0; index < PointCount(seeds); index++)
            addPoint.Invoke(augmented, new object[] { PointAt(seeds, index) });

        MethodInfo cellFacesCount = mesh.GetType().GetMethod(
            "CellFacesCount",
            new[] { typeof(int) }
        );
        MethodInfo cellFaces = mesh.GetType().GetMethod(
            "CellFaces",
            new[] { typeof(int) }
        );
        MethodInfo faceSimpleLength = mesh.GetType().GetMethod(
            "FaceSimpleLength",
            new[] { typeof(int) }
        );
        MethodInfo pointsOnFace = mesh.GetType().GetMethod(
            "PointsOnFace",
            new[] { typeof(int) }
        );
        MethodInfo faceSegment = mesh.GetType().GetMethod(
            "FaceSegment",
            new[] { typeof(int) }
        );
        if (
            cellFacesCount == null || cellFaces == null ||
            faceSimpleLength == null || pointsOnFace == null ||
            faceSegment == null
        )
            throw new MissingMethodException(
                mesh.GetType().FullName,
                "Max-faces repair mesh accessors"
            );

        int nonVirtualCellCount = Convert.ToInt32(
            Property(mesh, "NonVirtualCellCount")
        );
        HashSet<int> usedFaces = new HashSet<int>();
        added = 0;
        for (int cellIndex = 0; cellIndex < nonVirtualCellCount; cellIndex++)
        {
            int faceCount = Convert.ToInt32(
                cellFacesCount.Invoke(mesh, new object[] { cellIndex })
            );
            if (faceCount <= 8)
                continue;

            List<int> eligibleFaces = new List<int>();
            foreach (
                object faceValue in
                (IEnumerable)cellFaces.Invoke(mesh, new object[] { cellIndex })
            )
            {
                int faceIndex = Convert.ToInt32(faceValue);
                object facePoints = pointsOnFace.Invoke(
                    mesh,
                    new object[] { faceIndex }
                );
                if (PointCount(facePoints) <= 2)
                    eligibleFaces.Add(faceIndex);
            }
            eligibleFaces.Sort((left, right) =>
                Convert.ToDouble(
                    faceSimpleLength.Invoke(mesh, new object[] { right }),
                    CultureInfo.InvariantCulture
                ).CompareTo(
                    Convert.ToDouble(
                        faceSimpleLength.Invoke(mesh, new object[] { left }),
                        CultureInfo.InvariantCulture
                    )
                )
            );

            int addedForCell = 0;
            foreach (int faceIndex in eligibleFaces)
            {
                if (addedForCell >= 2)
                    break;
                if (!usedFaces.Add(faceIndex))
                    continue;
                object segment = faceSegment.Invoke(
                    mesh,
                    new object[] { faceIndex }
                );
                MethodInfo midpoint = segment.GetType().GetMethod(
                    "MidPoint",
                    Type.EmptyTypes
                );
                if (midpoint == null)
                    throw new MissingMethodException(
                        segment.GetType().FullName,
                        "MidPoint"
                    );
                addPoint.Invoke(
                    augmented,
                    new object[] { midpoint.Invoke(segment, null) }
                );
                added++;
                addedForCell++;
            }
        }
        return augmented;
    }

    private static double Coordinate(object point, string name)
    {
        PropertyInfo property = point.GetType().GetProperty(name);
        if (property != null)
            return Convert.ToDouble(property.GetValue(point, null));
        FieldInfo field = point.GetType().GetField(
            name,
            BindingFlags.Public | BindingFlags.NonPublic |
            BindingFlags.Instance
        );
        if (field != null)
            return Convert.ToDouble(field.GetValue(point));
        throw new MissingMemberException(point.GetType().FullName, name);
    }

    private static object ShiftPoints(object points, double dx, double dy)
    {
        Type pointMType = _assembly.GetType("RasMapperLib.PointM", true);
        Type pointMsType = _assembly.GetType("RasMapperLib.PointMs", true);
        object shifted = Activator.CreateInstance(pointMsType);
        MethodInfo add = pointMsType.GetMethods()
            .First(method =>
                method.Name == "Add" &&
                method.GetParameters().Length == 1 &&
                method.GetParameters()[0].ParameterType.IsAssignableFrom(
                    pointMType
                )
            );
        int count = PointCount(points);
        for (int index = 0; index < count; index++)
        {
            object point = PointAt(points, index);
            double x = Coordinate(point, "X");
            double y = Coordinate(point, "Y");
            object shiftedPoint = Activator.CreateInstance(
                pointMType,
                new object[] { x + dx, y + dy }
            );
            add.Invoke(shifted, new object[] { shiftedPoint });
        }
        return shifted;
    }

    private static object GenerateFallbackSeeds(
        object perimeter,
        double cellSize,
        Type generatorType
    )
    {
        if (
            Double.IsNaN(cellSize) ||
            Double.IsInfinity(cellSize) ||
            cellSize <= 0.0
        )
            throw new InvalidOperationException(
                "Cannot generate fallback mesh seeds with non-positive " +
                "Spacing dx: " +
                cellSize.ToString("R", CultureInfo.InvariantCulture)
            );

        int perimeterCount = PointCount(perimeter);
        if (perimeterCount < 3)
            throw new InvalidOperationException(
                "Cannot generate fallback mesh seeds for a perimeter with " +
                perimeterCount.ToString(CultureInfo.InvariantCulture) +
                " points"
            );
        double centerX = 0.0;
        double centerY = 0.0;
        for (int index = 0; index < perimeterCount; index++)
        {
            object point = PointAt(perimeter, index);
            centerX += Coordinate(point, "X");
            centerY += Coordinate(point, "Y");
        }
        centerX /= perimeterCount;
        centerY /= perimeterCount;

        Type polygonType = _assembly.GetType("RasMapperLib.Polygon", true);
        object generationPolygon = perimeter;
        bool shiftedToLocalCoordinates =
            Math.Abs(centerX) > 50000.0 || Math.Abs(centerY) > 50000.0;
        if (shiftedToLocalCoordinates)
        {
            object localPoints = ShiftPoints(perimeter, -centerX, -centerY);
            generationPolygon = Activator.CreateInstance(
                polygonType,
                new object[] { localPoints }
            );
        }

        MethodInfo generatePoints = generatorType.GetMethods(
            BindingFlags.Public | BindingFlags.Static
        ).Where(method =>
            method.Name == "GeneratePoints" &&
            (
                method.GetParameters().Length == 2 ||
                (
                    method.GetParameters().Length == 3 &&
                    method.GetParameters()[2].ParameterType == typeof(bool) &&
                    method.GetParameters()[2].IsOptional
                )
            ) &&
            method.GetParameters()[0].ParameterType.IsAssignableFrom(
                polygonType
            )
        ).OrderBy(method =>
            method.GetParameters()[0].ParameterType == polygonType ? 0 : 1
        ).First();
        Type spacingType = generatePoints.GetParameters()[1].ParameterType;
        object spacing = Convert.ChangeType(
            cellSize,
            spacingType,
            CultureInfo.InvariantCulture
        );
        object[] generateArguments = generatePoints.GetParameters().Length == 2
            ? new object[] { generationPolygon, spacing }
            : new object[] { generationPolygon, spacing, Type.Missing };
        object seeds = generatePoints.Invoke(null, generateArguments);
        return shiftedToLocalCoordinates
            ? ShiftPoints(seeds, centerX, centerY)
            : seeds;
    }

    private static bool DisableFileSystemWatcher(object instance)
    {
        if (instance == null)
            return false;
        for (Type type = instance.GetType(); type != null; type = type.BaseType)
        {
            FieldInfo watcherField = type.GetFields(
                BindingFlags.Public | BindingFlags.NonPublic |
                BindingFlags.Instance | BindingFlags.DeclaredOnly
            ).FirstOrDefault(field =>
                typeof(FileSystemWatcher).IsAssignableFrom(field.FieldType)
            );
            if (watcherField == null)
                continue;
            FileSystemWatcher watcher = watcherField.GetValue(instance)
                as FileSystemWatcher;
            if (watcher == null)
                return false;
            watcher.EnableRaisingEvents = false;
            // Wine's CLR can still dispatch a completion callback after
            // EnableRaisingEvents is cleared.  Disposing the watcher cancels
            // the underlying overlapped I/O before SaveMesh mutates the HDF;
            // this helper never needs live layer reload notifications.
            watcher.Dispose();
            return true;
        }
        return false;
    }

    private static Func<object, object> CompileObjectFieldGetter(FieldInfo field)
    {
        ParameterExpression instance = Expression.Parameter(
            typeof(object),
            "instance"
        );
        Expression value = Expression.Field(
            Expression.Convert(instance, field.DeclaringType),
            field
        );
        return Expression.Lambda<Func<object, object>>(
            Expression.Convert(value, typeof(object)),
            instance
        ).Compile();
    }

    private static Func<object, double> CompileDoubleFieldGetter(FieldInfo field)
    {
        ParameterExpression instance = Expression.Parameter(
            typeof(object),
            "instance"
        );
        Expression value = Expression.Field(
            Expression.Convert(instance, field.DeclaringType),
            field
        );
        return Expression.Lambda<Func<object, double>>(
            Expression.Convert(value, typeof(double)),
            instance
        ).Compile();
    }

    private static List<double[]> ExtractCellCenters(
        object mesh,
        Type meshType,
        int cellCount
    )
    {
        FieldInfo cellsField = meshType.GetField(
            "_cells",
            BindingFlags.NonPublic | BindingFlags.Instance
        );
        if (cellsField == null)
            throw new MissingFieldException(meshType.FullName, "_cells");
        Array cells = (Array)cellsField.GetValue(mesh);
        Type cellType = cells.GetType().GetElementType();
        FieldInfo pointField = cellType.GetField(
            "Point",
            BindingFlags.Public | BindingFlags.NonPublic |
            BindingFlags.Instance
        );
        if (pointField == null)
            throw new MissingFieldException(cellType.FullName, "Point");
        Type pointType = pointField.FieldType;
        FieldInfo xField = pointType.GetField(
            "X",
            BindingFlags.Public | BindingFlags.NonPublic |
            BindingFlags.Instance
        );
        FieldInfo yField = pointType.GetField(
            "Y",
            BindingFlags.Public | BindingFlags.NonPublic |
            BindingFlags.Instance
        );
        if (xField == null || yField == null)
            throw new MissingFieldException(
                pointType.FullName,
                xField == null ? "X" : "Y"
            );
        Func<object, object> getPoint = CompileObjectFieldGetter(pointField);
        Func<object, double> getX = CompileDoubleFieldGetter(xField);
        Func<object, double> getY = CompileDoubleFieldGetter(yField);
        List<double[]> centers = new List<double[]>();
        foreach (object cell in cells)
        {
            if (centers.Count >= cellCount)
                break;
            object point = getPoint(cell);
            centers.Add(new[] { getX(point), getY(point) });
        }
        if (centers.Count != cellCount)
            throw new IOException(
                "Mesh cell-center extraction returned " +
                centers.Count.ToString(CultureInfo.InvariantCulture) +
                " rows; expected " +
                cellCount.ToString(CultureInfo.InvariantCulture)
            );
        return centers;
    }

    private static void Stage(string value)
    {
        Console.Error.WriteLine("mesh-host-stage: " + value);
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

    private static int CompleteMeshCellCount(object d2FlowArea, int fid)
    {
        MethodInfo meshMethod = d2FlowArea.GetType().GetMethods(
            BindingFlags.Public | BindingFlags.Instance
        ).Single(method =>
            method.Name == "Mesh" &&
            method.GetParameters().Length == 1 &&
            method.GetParameters()[0].ParameterType == typeof(int)
        );
        object areaMesh = meshMethod.Invoke(
            d2FlowArea,
            new object[] { fid }
        );
        if (areaMesh == null)
            return 0;
        MethodInfo isComplete = areaMesh.GetType().GetMethod(
            "IsComplete",
            BindingFlags.Public | BindingFlags.Instance,
            null,
            Type.EmptyTypes,
            null
        );
        if (isComplete == null || !(bool)isComplete.Invoke(areaMesh, null))
            return 0;
        return Convert.ToInt32(
            Property(areaMesh, "NonVirtualCellCount"),
            CultureInfo.InvariantCulture
        );
    }

    private static ReloadSuppressorHandle CreateReloadSuppressor(
        object d2FlowArea,
        PersistenceReceipt persistence
    )
    {
        Type suppressorType = _assembly.GetType(
            "RasMapperLib.FeatureTableReloadSuppressor",
            true
        );
        ConstructorInfo constructor = suppressorType.GetConstructors(
            BindingFlags.Public | BindingFlags.Instance
        ).Single(candidate =>
            candidate.GetParameters().Length == 1 &&
            candidate.GetParameters()[0].ParameterType.IsAssignableFrom(
                d2FlowArea.GetType()
            )
        );
        object suppressor = constructor.Invoke(
            new object[] { d2FlowArea }
        );
        IDisposable disposable = suppressor as IDisposable;
        if (disposable == null)
            throw new InvalidCastException(
                suppressorType.FullName + " does not implement IDisposable"
            );
        persistence.ReloadSuppressorCreated = true;
        persistence.ReloadSuppressorType = suppressorType.FullName;
        Stage("feature-table-reload-suppressor-created");
        return new ReloadSuppressorHandle(disposable);
    }

    private static object CellCountAwareDatatableManager(
        object d2FlowArea,
        object d2Manager,
        object perimeterManager,
        int targetFid,
        int expectedCellCount,
        PersistenceReceipt persistence
    )
    {
        Type managerType = d2Manager.GetType();
        object cellCountManager = Activator.CreateInstance(managerType, true);
        MethodInfo addWriteOnly = managerType.GetMethods(
            BindingFlags.Public | BindingFlags.Instance
        ).Single(method =>
            method.Name == "AddWriteOnly" &&
            method.IsGenericMethodDefinition &&
            method.GetGenericArguments().Length == 1 &&
            method.GetParameters().Length == 2 &&
            method.GetParameters()[0].ParameterType == typeof(string)
        ).MakeGenericMethod(typeof(int));

        // RASD2FlowArea registers Cell Count as a managed write-only column,
        // so it is intentionally absent from FeatureTable().  Put an exact
        // product-state-backed serializer first: DatatableLoadManager.Merge
        // retains the first callback for a duplicate disk column name.  This
        // is the vendor serialization API, not a raw HDF field patch.
        int targetCellCount = CompleteMeshCellCount(
            d2FlowArea,
            targetFid
        );
        if (targetCellCount != expectedCellCount)
            throw new IOException(
                "RASD2FlowArea managed Cell Count changed before serializer " +
                "binding for FID " +
                targetFid.ToString(CultureInfo.InvariantCulture)
            );
        Func<int, int> cellCount = rowFid =>
            CompleteMeshCellCount(d2FlowArea, rowFid);
        addWriteOnly.Invoke(
            cellCountManager,
            new object[] { "Cell Count", cellCount }
        );

        MethodInfo merge = managerType.GetMethods(
            BindingFlags.Public | BindingFlags.Instance
        ).Single(method =>
            method.Name == "Merge" &&
            method.GetParameters().Length == 1 &&
            method.GetParameters()[0].ParameterType.IsAssignableFrom(
                managerType
            )
        );
        object mergedManager = merge.Invoke(
            cellCountManager,
            new object[] { d2Manager }
        );
        mergedManager = merge.Invoke(
            mergedManager,
            new object[] { perimeterManager }
        );
        persistence.CellCountSerializerOverrideRegistered = true;

        FieldInfo memoryMapField = managerType.GetField(
            "_h5MemoryMap",
            BindingFlags.NonPublic | BindingFlags.Instance
        );
        if (memoryMapField == null)
            throw new MissingFieldException(managerType.FullName, "_h5MemoryMap");
        object memoryMap = memoryMapField.GetValue(mergedManager);
        FieldInfo writeNamesField = memoryMap.GetType().GetField(
            "_writeColumnNames",
            BindingFlags.NonPublic | BindingFlags.Instance
        );
        if (writeNamesField == null)
            throw new MissingFieldException(
                memoryMap.GetType().FullName,
                "_writeColumnNames"
            );
        IList writeNames = (IList)writeNamesField.GetValue(memoryMap);
        List<int> cellCountIndexes = new List<int>();
        for (int index = 0; index < writeNames.Count; index++)
        {
            if (Convert.ToString(
                writeNames[index],
                CultureInfo.InvariantCulture
            ) == "Cell Count")
                cellCountIndexes.Add(index);
        }
        if (cellCountIndexes.Count != 1 || cellCountIndexes[0] != 0)
            throw new IOException(
                "RasMapperLib did not retain the exact Cell Count serializer " +
                "as the first unique write column"
            );
        persistence.CellCountSerializerFirstVerified = true;
        return mergedManager;
    }

    private static void WriteMeshDirectly(
        object geometry,
        object d2FlowArea,
        object perimeters,
        object mesh,
        Type meshType,
        string hdfPath,
        string meshName,
        int meshFid,
        int expectedCellCount,
        int expectedFaceCount,
        List<double[]> expectedCellCenters,
        bool forceSave,
        string receiptPath,
        string meshState,
        int seedCount,
        int constraintCount,
        int temporaryStructureBreaklines,
        int fileSystemWatchersDisabled,
        List<RefinementRegionReceipt> refinementRegions,
        ReloadSuppressorHandle reloadSuppressor,
        PersistenceReceipt persistence
    )
    {
        if (reloadSuppressor == null || reloadSuppressor.IsDisposed)
            throw new InvalidOperationException(
                "Transactional mesh persistence requires an active " +
                "FeatureTableReloadSuppressor"
            );
        Stage("transactional-save-started");
        Assembly h5Assist = Assembly.LoadFrom(
            Path.Combine(_hecrasDir, "H5Assist.dll")
        );
        Type writerType = h5Assist.GetType("H5Assist.H5Writer", true);
        ConstructorInfo writerConstructor = writerType.GetConstructor(
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
            null,
            new[] { typeof(string), typeof(bool) },
            null
        );
        if (writerConstructor == null)
            throw new MissingMethodException(
                writerType.FullName,
                ".ctor(string, bool)"
            );

        MethodInfo saveMesh = meshType.GetMethods(
            BindingFlags.Public | BindingFlags.Instance
        ).Where(method =>
            method.Name == "SaveMesh" &&
            (method.GetParameters().Length == 4 ||
             method.GetParameters().Length == 5) &&
            method.GetParameters()[0].ParameterType.FullName ==
                "H5Assist.H5Writer" &&
            method.GetParameters()[1].ParameterType == typeof(string) &&
            method.GetParameters()[2].ParameterType == typeof(string)
        ).OrderByDescending(method => method.GetParameters().Length).FirstOrDefault();
        if (saveMesh == null)
            throw new MissingMethodException(
                meshType.FullName,
                "SaveMesh(H5Writer, string, string, ProgressReporter[, bool])"
            );
        ParameterInfo[] saveParameters = saveMesh.GetParameters();
        persistence.SaveMeshParameterCount = saveParameters.Length;
        persistence.SaveMeshForce = forceSave;

        object writer = null;
        try
        {
            writer = writerConstructor.Invoke(
                new object[] { hdfPath, true }
            );
            object d2Manager = Property(d2FlowArea, "DatatableManager");
            object perimeterManager = Property(perimeters, "DatatableManager");
            MethodInfo featureTable = d2FlowArea.GetType().GetMethods(
                BindingFlags.Public | BindingFlags.Instance
            ).Single(method =>
                method.Name == "FeatureTable" &&
                method.GetParameters().Length == 0
            );
            System.Data.DataTable table = (System.Data.DataTable)
                featureTable.Invoke(d2FlowArea, null);
            persistence.FeatureTableContainsCellCountColumn =
                table.Columns.Contains("Cell Count");
            if (!table.Columns.Contains("FID") || !table.Columns.Contains("Name"))
                throw new IOException(
                    "2D flow-area feature table lacks FID or Name"
                );
            List<System.Data.DataRow> targetRows = table.Rows
                .Cast<System.Data.DataRow>()
                .Where(row => Convert.ToInt32(
                    row["FID"],
                    CultureInfo.InvariantCulture
                ) == meshFid)
                .ToList();
            if (targetRows.Count != 1)
                throw new IOException(
                    "2D flow-area feature table does not contain exactly one " +
                    "target FID for " + meshName
                );
            System.Data.DataRow targetRow = targetRows[0];
            int rowFid = Convert.ToInt32(
                targetRow["FID"],
                CultureInfo.InvariantCulture
            );
            string rowName = Convert.ToString(
                targetRow["Name"],
                CultureInfo.InvariantCulture
            );
            if (rowFid != meshFid || rowName != meshName)
                throw new IOException(
                    "2D flow-area feature-table target mismatch for " + meshName
                );
            int generatedCellCount = Convert.ToInt32(
                    Property(mesh, "NonVirtualCellCount"),
                    CultureInfo.InvariantCulture
                );
            int generatedFaceCount = Convert.ToInt32(
                Property(mesh, "FaceCount"),
                CultureInfo.InvariantCulture
            );
            MethodInfo isComplete = meshType.GetMethod(
                "IsComplete",
                BindingFlags.Public | BindingFlags.Instance,
                null,
                Type.EmptyTypes,
                null
            );
            bool generatedComplete =
                isComplete != null && (bool)isComplete.Invoke(mesh, null);
            if (
                generatedCellCount != expectedCellCount ||
                generatedFaceCount != expectedFaceCount ||
                !generatedComplete
            )
                throw new IOException(
                    "Generated product mesh is not complete at feature-table write"
                );

            MethodInfo layerMeshMethod = d2FlowArea.GetType().GetMethods(
                BindingFlags.Public | BindingFlags.Instance
            ).Single(method =>
                method.Name == "Mesh" &&
                method.GetParameters().Length == 1 &&
                method.GetParameters()[0].ParameterType == typeof(int)
            );
            object layerMesh = layerMeshMethod.Invoke(
                d2FlowArea,
                new object[] { meshFid }
            );
            persistence.LayerMeshReferenceMatchesGenerated =
                Object.ReferenceEquals(layerMesh, mesh);
            if (layerMesh != null)
            {
                MethodInfo layerIsComplete = layerMesh.GetType().GetMethod(
                    "IsComplete",
                    BindingFlags.Public | BindingFlags.Instance,
                    null,
                    Type.EmptyTypes,
                    null
                );
                persistence.LayerMeshComplete =
                    layerIsComplete != null &&
                    (bool)layerIsComplete.Invoke(layerMesh, null);
                if (persistence.LayerMeshComplete)
                {
                    persistence.LayerMeshCellCount = Convert.ToInt32(
                        Property(layerMesh, "NonVirtualCellCount"),
                        CultureInfo.InvariantCulture
                    );
                    persistence.LayerMeshFaceCount = Convert.ToInt32(
                        Property(layerMesh, "FaceCount"),
                        CultureInfo.InvariantCulture
                    );
                }
            }
            persistence.VendorManagedCellCountBeforeOverride =
                CompleteMeshCellCount(d2FlowArea, meshFid);
            if (
                !persistence.LayerMeshReferenceMatchesGenerated ||
                !persistence.LayerMeshComplete ||
                persistence.LayerMeshCellCount != expectedCellCount ||
                persistence.LayerMeshFaceCount != expectedFaceCount ||
                persistence.VendorManagedCellCountBeforeOverride !=
                    expectedCellCount
            )
                throw new IOException(
                    "RASD2FlowArea.Mesh target does not exactly match the " +
                    "generated product mesh at feature-table write"
                );
            persistence.FeatureTableTargetValidated = true;
            persistence.FeatureTableTargetFid = meshFid;
            persistence.FeatureTableTargetCellCount = expectedCellCount;

            object mergedManager = CellCountAwareDatatableManager(
                d2FlowArea,
                d2Manager,
                perimeterManager,
                meshFid,
                expectedCellCount,
                persistence
            );
            Stage("feature-table-cell-count-bound");
            MethodInfo write = mergedManager.GetType().GetMethods(
                BindingFlags.Public | BindingFlags.Instance
            ).Single(method =>
                method.Name == "Write" &&
                method.GetParameters().Length == 3 &&
                method.GetParameters()[0].ParameterType.FullName ==
                    "H5Assist.H5Writer" &&
                method.GetParameters()[1].ParameterType == typeof(string) &&
                method.GetParameters()[2].ParameterType ==
                    typeof(System.Data.DataTable)
            );
            write.Invoke(
                mergedManager,
                new object[] {
                    writer,
                    "Geometry/2D Flow Areas/Attributes",
                    table
                }
            );
            persistence.FeatureTableWritten = true;
            Stage("feature-table-written");

            object meshPointsLayer = Property(geometry, "MeshPoints");
            MethodInfo saveMeshPointsTable = meshPointsLayer.GetType()
                .GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .Single(method =>
                    method.Name == "HDFSaveFeatureTable" &&
                    method.GetParameters().Length == 1 &&
                    method.GetParameters()[0].ParameterType.FullName ==
                        "H5Assist.H5Writer"
                );
            saveMeshPointsTable.Invoke(
                meshPointsLayer,
                new object[] { writer }
            );
            persistence.MeshPointsFeatureTableWritten = true;
            Stage("mesh-points-feature-table-written");

            // MeshPointLayer shares the 2D-flow-area HDF group and its public
            // save rewrites the common Attributes dataset from its own table.
            // Restore the exact D2/perimeter manager projection after the cell
            // point datasets are written.
            write.Invoke(
                mergedManager,
                new object[] {
                    writer,
                    "Geometry/2D Flow Areas/Attributes",
                    table
                }
            );
            persistence.FeatureTableRestoredAfterMeshPoints = true;
            Stage("feature-table-restored-after-mesh-points");

            // SaveMesh is the unstable Wine boundary.  Persist the complete
            // product-generated center payload before entering it so the
            // parent can validate a candidate after a fatal CLR exit or a
            // bounded kill.  This receipt alone never authorizes replacement;
            // every HDF topology and ordered-center check must still pass.
            WriteReceipt(
                receiptPath,
                "generated-awaiting-persistence",
                meshState,
                seedCount,
                expectedCellCount,
                expectedFaceCount,
                constraintCount,
                temporaryStructureBreaklines,
                fileSystemWatchersDisabled,
                refinementRegions,
                expectedCellCenters,
                true,
                false,
                persistence,
                ""
            );
            Stage("persistence-attempt-checkpoint-written");

            Type dssType = _assembly.GetType(
                "RasMapperLib.Utilities.DSS",
                true
            );
            MethodInfo convertDate = dssType.GetMethods(
                BindingFlags.Public | BindingFlags.Static
            ).Single(method =>
                method.Name == "ConvertToDSSDateTime" &&
                method.GetParameters().Length == 1 &&
                method.GetParameters()[0].ParameterType == typeof(DateTime)
            );
            string dssDateTime = Convert.ToString(
                convertDate.Invoke(null, new object[] { DateTime.Now }),
                CultureInfo.InvariantCulture
            );
            Type progressType = saveParameters[3].ParameterType;
            MethodInfo none = progressType.GetMethods(
                BindingFlags.Public | BindingFlags.Static
            ).Single(method =>
                method.Name == "None" &&
                method.GetParameters().Length == 0
            );
            object progress = none.Invoke(null, null);
            object[] saveArguments = saveParameters.Length == 5
                ? new object[] {
                    writer,
                    meshName,
                    dssDateTime,
                    progress,
                    forceSave
                }
                : new object[] { writer, meshName, dssDateTime, progress };
            Stage(
                "mesh-save-overload-" +
                saveParameters.Length.ToString(CultureInfo.InvariantCulture)
            );
            saveMesh.Invoke(mesh, saveArguments);
            Stage("mesh-save-returned");
            persistence.WriterFlushAttempted = true;
            try
            {
                writerType.GetMethod(
                    "Flush",
                    BindingFlags.Public | BindingFlags.Instance
                ).Invoke(writer, null);
                persistence.WriterFlushSucceeded = true;
            }
            catch (Exception flushException)
            {
                Exception root = Unwrap(flushException);
                persistence.WriterFlushError =
                    root.GetType().FullName + ": " + root.Message;
                Stage("writer-flush-failed");
            }
            Stage("mesh-save-completed");
        }
        finally
        {
            try
            {
                IDisposable disposable = writer as IDisposable;
                if (disposable != null)
                    disposable.Dispose();
                Stage("writer-closed");
            }
            finally
            {
                reloadSuppressor.Dispose();
                persistence.ReloadSuppressorDisposed = true;
                persistence.ReloadSuppressorDisposedBeforeReopen = true;
                Stage("feature-table-reload-suppressor-disposed");
            }
        }

        if (!reloadSuppressor.IsDisposed)
            throw new InvalidOperationException(
                "FeatureTableReloadSuppressor remained active before reopen"
            );
        WriteReceipt(
            receiptPath,
            "persisted-awaiting-validation",
            meshState,
            seedCount,
            expectedCellCount,
            expectedFaceCount,
            constraintCount,
            temporaryStructureBreaklines,
            fileSystemWatchersDisabled,
            refinementRegions,
            expectedCellCenters,
            true,
            true,
            persistence,
            ""
        );
        Stage("validation-checkpoint-written");
        Stage("validation-reopen-started");
        Type geometryType = _assembly.GetType(
            "RasMapperLib.RASGeometry",
            true
        );
        object reopenedGeometry = Activator.CreateInstance(
            geometryType,
            new object[] { hdfPath }
        );
        Stage("validation-geometry-opened");
        object reopenedD2FlowArea = Property(reopenedGeometry, "D2FlowArea");
        if (DisableFileSystemWatcher(reopenedD2FlowArea))
        {
            // This validation instance is intentionally independent of the
            // writer instance; disabling its watcher avoids headless churn.
        }
        MethodInfo getFeatureByName = reopenedD2FlowArea.GetType().GetMethods()
            .Single(method =>
                method.Name == "GetFeatureByName" &&
                method.GetParameters().Length == 1 &&
                method.GetParameters()[0].ParameterType == typeof(string)
            );
        int reopenedFid = Convert.ToInt32(
            getFeatureByName.Invoke(
                reopenedD2FlowArea,
                new object[] { meshName }
            )
        );
        if (reopenedFid < 0)
            throw new IOException(
                "Direct mesh save did not persist flow-area attributes for " +
                meshName
            );
        MethodInfo meshMethod = reopenedD2FlowArea.GetType().GetMethods()
            .Single(method =>
                method.Name == "Mesh" &&
                method.GetParameters().Length == 1 &&
                method.GetParameters()[0].ParameterType == typeof(int)
            );
        object reopenedMesh = meshMethod.Invoke(
            reopenedD2FlowArea,
            new object[] { reopenedFid }
        );
        if (reopenedMesh == null)
            throw new IOException(
                "Direct mesh save returned no mesh after reopen for " + meshName
            );
        string reopenedState = Convert.ToString(
            Property(reopenedMesh, "MeshCompletionState"),
            CultureInfo.InvariantCulture
        );
        persistence.ReopenedCellCount = Convert.ToInt32(
            Property(reopenedMesh, "NonVirtualCellCount")
        );
        persistence.ReopenedFaceCount = Convert.ToInt32(
            Property(reopenedMesh, "FaceCount")
        );
        if (
            reopenedState != "Complete" ||
            persistence.ReopenedCellCount != expectedCellCount ||
            persistence.ReopenedFaceCount != expectedFaceCount
        )
            throw new IOException(
                "Direct mesh save topology mismatch after reopen for " +
                meshName + ": expected " +
                expectedCellCount.ToString(CultureInfo.InvariantCulture) +
                " cells/" +
                expectedFaceCount.ToString(CultureInfo.InvariantCulture) +
                " faces, observed " +
                persistence.ReopenedCellCount.ToString(
                    CultureInfo.InvariantCulture
                ) + " cells/" +
                persistence.ReopenedFaceCount.ToString(
                    CultureInfo.InvariantCulture
                ) + " faces (state " + reopenedState + ")"
            );
        persistence.ReopenedTopologyValidated = true;
        Stage("validation-topology-matched");

        List<double[]> reopenedCenters = ExtractCellCenters(
            reopenedMesh,
            meshType,
            expectedCellCount
        );
        if (expectedCellCenters.Count != expectedCellCount)
            throw new IOException(
                "Generated center payload is incomplete before reopen validation"
            );
        double maxAbsError = 0.0;
        for (int index = 0; index < expectedCellCount; index++)
        {
            for (int ordinate = 0; ordinate < 2; ordinate++)
            {
                double expected = expectedCellCenters[index][ordinate];
                double observed = reopenedCenters[index][ordinate];
                if (
                    Double.IsNaN(expected) || Double.IsInfinity(expected) ||
                    Double.IsNaN(observed) || Double.IsInfinity(observed)
                )
                    throw new IOException(
                        "Non-finite mesh center encountered during reopen validation"
                    );
                maxAbsError = Math.Max(
                    maxAbsError,
                    Math.Abs(expected - observed)
                );
            }
        }
        persistence.ReopenedCenterMaxAbsError = maxAbsError;
        if (maxAbsError > 1e-8)
            throw new IOException(
                "Direct mesh save center mismatch after reopen for " +
                meshName + ": max absolute error " +
                maxAbsError.ToString("R", CultureInfo.InvariantCulture)
            );
        persistence.ReopenedCentersValidated = true;
        Stage("validation-centers-matched");
    }

    private static void WriteReceipt(
        string path,
        string status,
        string meshState,
        int seedCount,
        int cellCount,
        int faceCount,
        int constraintCount,
        int temporaryStructureBreaklines,
        int fileSystemWatchersDisabled,
        List<RefinementRegionReceipt> refinementRegions,
        List<double[]> cellCenters,
        bool hdfSaveRequested,
        bool meshSaved,
        PersistenceReceipt persistence,
        string error
    )
    {
        StringBuilder centersJson = new StringBuilder("[");
        for (int index = 0; index < cellCenters.Count; index++)
        {
            if (index > 0)
                centersJson.Append(',');
            centersJson.Append('[');
            centersJson.Append(
                cellCenters[index][0].ToString("R", CultureInfo.InvariantCulture)
            );
            centersJson.Append(',');
            centersJson.Append(
                cellCenters[index][1].ToString("R", CultureInfo.InvariantCulture)
            );
            centersJson.Append(']');
        }
        centersJson.Append(']');
        StringBuilder regionsJson = new StringBuilder("[");
        for (int index = 0; index < refinementRegions.Count; index++)
        {
            if (index > 0)
                regionsJson.Append(',');
            RefinementRegionReceipt region = refinementRegions[index];
            regionsJson.Append('{');
            regionsJson.Append(
                "\"fid\":" + region.Fid.ToString(CultureInfo.InvariantCulture)
            );
            regionsJson.Append(
                ",\"name\":\"" + JsonEscape(region.Name) + "\""
            );
            regionsJson.Append(
                ",\"spacing_dx\":" +
                region.SpacingDx.ToString("R", CultureInfo.InvariantCulture)
            );
            regionsJson.Append(
                ",\"spacing_dy\":" +
                region.SpacingDy.ToString("R", CultureInfo.InvariantCulture)
            );
            regionsJson.Append(
                ",\"point_count\":" +
                region.PointCount.ToString(CultureInfo.InvariantCulture)
            );
            regionsJson.Append('}');
        }
        regionsJson.Append(']');
        string fixesJson = "[" + String.Join(
            ",",
            persistence.FixesApplied.Select(value =>
                "\"" + JsonEscape(value) + "\""
            ).ToArray()
        ) + "]";
        string json = "{" +
            "\"backend\":\"managed_host\"," +
            "\"status\":\"" + JsonEscape(status) + "\"," +
            "\"mesh_state\":\"" + JsonEscape(meshState) + "\"," +
            "\"mesh_iterations\":" +
                persistence.MeshIterations.ToString(
                    CultureInfo.InvariantCulture
                ) + "," +
            "\"fixes_applied\":" + fixesJson + "," +
            "\"seed_count\":" + seedCount.ToString(CultureInfo.InvariantCulture) + "," +
            "\"cell_count\":" + cellCount.ToString(CultureInfo.InvariantCulture) + "," +
            "\"face_count\":" + faceCount.ToString(CultureInfo.InvariantCulture) + "," +
            "\"constraint_count\":" + constraintCount.ToString(CultureInfo.InvariantCulture) + "," +
            "\"temporary_structure_breaklines\":" +
                temporaryStructureBreaklines.ToString(CultureInfo.InvariantCulture) + "," +
            "\"filesystem_watchers_disabled\":" +
                fileSystemWatchersDisabled.ToString(CultureInfo.InvariantCulture) + "," +
            "\"refinement_regions\":" + regionsJson.ToString() + "," +
            "\"cell_centers_extracted\":" +
                (cellCenters.Count == cellCount && cellCount > 0 ? "true" : "false") + "," +
            "\"cell_centers\":" + centersJson.ToString() + "," +
            "\"hdf_save_requested\":" + (hdfSaveRequested ? "true" : "false") + "," +
            "\"mesh_saved\":" + (meshSaved ? "true" : "false") + "," +
            "\"hdf_persistence_mode\":\"" +
                JsonEscape(persistence.Mode) + "\"," +
            "\"reload_suppressor_created\":" +
                (persistence.ReloadSuppressorCreated ? "true" : "false") + "," +
            "\"reload_suppressor_disposed\":" +
                (persistence.ReloadSuppressorDisposed ? "true" : "false") + "," +
            "\"reload_suppressor_disposed_before_reopen\":" +
                (persistence.ReloadSuppressorDisposedBeforeReopen
                    ? "true"
                    : "false") + "," +
            "\"reload_suppressor_type\":\"" +
                JsonEscape(persistence.ReloadSuppressorType) + "\"," +
            "\"set_feature_returned_data_row\":" +
                (persistence.SetFeatureReturnedDataRow ? "true" : "false") + "," +
            "\"set_feature_row_reference_matches_generated\":" +
                (persistence.SetFeatureRowReferenceMatchesGenerated
                    ? "true"
                    : "false") + "," +
            "\"set_feature_column_name\":\"" +
                JsonEscape(persistence.SetFeatureColumnName) + "\"," +
            "\"feature_table_written\":" +
                (persistence.FeatureTableWritten ? "true" : "false") + "," +
            "\"feature_table_target_validated\":" +
                (persistence.FeatureTableTargetValidated ? "true" : "false") + "," +
            "\"mesh_points_set_feature_returned_data_row\":" +
                (persistence.MeshPointsSetFeatureReturnedDataRow
                    ? "true"
                    : "false") + "," +
            "\"mesh_points_set_feature_row_reference_matches_generated\":" +
                (persistence.MeshPointsSetFeatureRowReferenceMatchesGenerated
                    ? "true"
                    : "false") + "," +
            "\"mesh_points_feature_table_written\":" +
                (persistence.MeshPointsFeatureTableWritten
                    ? "true"
                    : "false") + "," +
            "\"feature_table_restored_after_mesh_points\":" +
                (persistence.FeatureTableRestoredAfterMeshPoints
                    ? "true"
                    : "false") + "," +
            "\"cell_count_serializer_override_registered\":" +
                (persistence.CellCountSerializerOverrideRegistered ? "true" : "false") + "," +
            "\"cell_count_serializer_first_verified\":" +
                (persistence.CellCountSerializerFirstVerified ? "true" : "false") + "," +
            "\"feature_table_contains_cell_count_column\":" +
                (persistence.FeatureTableContainsCellCountColumn ? "true" : "false") + "," +
            "\"layer_mesh_reference_matches_generated\":" +
                (persistence.LayerMeshReferenceMatchesGenerated ? "true" : "false") + "," +
            "\"layer_mesh_complete\":" +
                (persistence.LayerMeshComplete ? "true" : "false") + "," +
            "\"layer_mesh_cell_count\":" +
                persistence.LayerMeshCellCount.ToString(
                    CultureInfo.InvariantCulture
                ) + "," +
            "\"layer_mesh_face_count\":" +
                persistence.LayerMeshFaceCount.ToString(
                    CultureInfo.InvariantCulture
                ) + "," +
            "\"vendor_managed_cell_count_before_override\":" +
                persistence.VendorManagedCellCountBeforeOverride.ToString(
                    CultureInfo.InvariantCulture
                ) + "," +
            "\"feature_table_target_fid\":" +
                persistence.FeatureTableTargetFid.ToString(
                    CultureInfo.InvariantCulture
                ) + "," +
            "\"feature_table_target_cell_count\":" +
                persistence.FeatureTableTargetCellCount.ToString(
                    CultureInfo.InvariantCulture
                ) + "," +
            "\"save_mesh_parameter_count\":" +
                persistence.SaveMeshParameterCount.ToString(
                    CultureInfo.InvariantCulture
                ) + "," +
            "\"save_mesh_force\":" +
                (persistence.SaveMeshForce ? "true" : "false") + "," +
            "\"writer_flush_attempted\":" +
                (persistence.WriterFlushAttempted ? "true" : "false") + "," +
            "\"writer_flush_succeeded\":" +
                (persistence.WriterFlushSucceeded ? "true" : "false") + "," +
            "\"writer_flush_error\":\"" +
                JsonEscape(persistence.WriterFlushError) + "\"," +
            "\"seed_generation_method\":\"" +
                JsonEscape(persistence.SeedGenerationMethod) + "\"," +
            "\"seed_fallback_used\":" +
                (persistence.SeedFallbackUsed ? "true" : "false") + "," +
            "\"seed_fallback_cell_size\":" +
                persistence.SeedFallbackCellSize.ToString(
                    "R",
                    CultureInfo.InvariantCulture
                ) + "," +
            "\"regenerate_parameter_signature\":\"" +
                JsonEscape(persistence.RegenerateParameterSignature) + "\"," +
            "\"reopened_topology_validated\":" +
                (persistence.ReopenedTopologyValidated ? "true" : "false") + "," +
            "\"reopened_cell_count\":" +
                persistence.ReopenedCellCount.ToString(
                    CultureInfo.InvariantCulture
                ) + "," +
            "\"reopened_face_count\":" +
                persistence.ReopenedFaceCount.ToString(
                    CultureInfo.InvariantCulture
                ) + "," +
            "\"reopened_centers_validated\":" +
                (persistence.ReopenedCentersValidated ? "true" : "false") + "," +
            "\"reopened_center_max_abs_error\":" +
                persistence.ReopenedCenterMaxAbsError.ToString(
                    "R",
                    CultureInfo.InvariantCulture
                ) + "," +
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

    public static int Main(string[] args)
    {
        if (args.Length != 7)
        {
            Console.Error.WriteLine(
                "Usage: RasMapperMeshHelper.exe HECRAS_DIR GEOMETRY_HDF " +
                "MESH_NAME MIN_FACE_LENGTH_RATIO CELL_SIZE RECEIPT_JSON " +
                "PERSISTENCE_MODE"
            );
            return 2;
        }

        _hecrasDir = args[0];
        string hdfPath = args[1];
        string meshName = args[2];
        double minFaceLengthRatio = double.Parse(
            args[3],
            CultureInfo.InvariantCulture
        );
        double requestedCellSize = double.Parse(
            args[4],
            CultureInfo.InvariantCulture
        );
        string receiptPath = args[5];
        string persistenceMode = args[6].Trim().ToLowerInvariant();
        if (persistenceMode == "true")
            persistenceMode = "legacy_save";
        else if (persistenceMode == "false")
            persistenceMode = "skip";
        if (
            persistenceMode != "skip" &&
            persistenceMode != "legacy_save" &&
            persistenceMode != "transactional_direct"
        )
        {
            Console.Error.WriteLine(
                "PERSISTENCE_MODE must be skip, legacy_save, or " +
                "transactional_direct."
            );
            return 2;
        }
        bool hdfSaveRequested = persistenceMode != "skip";
        string seedGenerationMode = (
            Environment.GetEnvironmentVariable("RAS_MESH_SEED_GENERATION_MODE") ??
            "regenerate_then_fallback"
        ).Trim().ToLowerInvariant();
        if (
            seedGenerationMode != "regenerate_then_fallback" &&
            seedGenerationMode != "point_generator"
        )
        {
            Console.Error.WriteLine(
                "RAS_MESH_SEED_GENERATION_MODE must be " +
                "regenerate_then_fallback or point_generator."
            );
            return 2;
        }
        _progressPath = receiptPath + ".progress";
        if (File.Exists(_progressPath))
            File.Delete(_progressPath);
        int seedCount = 0;
        int cellCount = 0;
        int faceCount = 0;
        int constraintCount = 0;
        int temporaryStructureBreaklines = 0;
        int fileSystemWatchersDisabled = 0;
        int preexistingMeshCellCount = 0;
        List<RefinementRegionReceipt> refinementRegions =
            new List<RefinementRegionReceipt>();
        List<double[]> cellCenters = new List<double[]>();
        string meshState = "";
        bool meshSaved = false;
        PersistenceReceipt persistence = new PersistenceReceipt {
            Mode = persistenceMode
        };

        try
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
                    "RasMapperMeshHelper.exe: " + applicationGdal
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

            _assembly = Assembly.LoadFrom(
                Path.Combine(_hecrasDir, "RasMapperLib.dll")
            );
            Type geometryType = _assembly.GetType(
                "RasMapperLib.RASGeometry",
                true
            );
            object geometry = Activator.CreateInstance(
                geometryType,
                new object[] { hdfPath }
            );
            Stage("geometry-opened");
            object d2FlowArea = Property(geometry, "D2FlowArea");
            if (DisableFileSystemWatcher(d2FlowArea))
                fileSystemWatchersDisabled++;
            Stage("d2-flow-area-ready");
            MethodInfo getFeatureByName = d2FlowArea.GetType().GetMethods()
                .Single(method =>
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
            preexistingMeshCellCount = CompleteMeshCellCount(d2FlowArea, fid);

            object layerGeometry = Property(d2FlowArea, "Geometry");
            object perimeters = Property(layerGeometry, "MeshPerimeters");
            MethodInfo getPolygon = perimeters.GetType().GetMethods()
                .Single(method =>
                    method.Name == "Polygon" &&
                    method.GetParameters().Length == 1 &&
                    method.GetParameters()[0].ParameterType == typeof(int)
                );
            object perimeter = getPolygon.Invoke(
                perimeters,
                new object[] { fid }
            );
            if (perimeter == null || Convert.ToInt32(Property(perimeter, "Count")) == 0)
                throw new InvalidOperationException(
                    "RASGeometry returned an empty mesh perimeter for " + meshName
                );

            object breaklineLayer = Property(geometry, "BreakLines");
            object structureLayer = Property(geometry, "SA2DStructures");
            if (DisableFileSystemWatcher(breaklineLayer))
                fileSystemWatchersDisabled++;
            if (DisableFileSystemWatcher(structureLayer))
                fileSystemWatchersDisabled++;
            List<int> temporaryBreaklineFids = new List<int>();
            string[] spacingColumns = new[] {
                "Near Spacing",
                "Far Spacing",
                "Near Repeats",
                "Enforce 1 Cell Protection Radius"
            };
            foreach (int structureFid in FeatureIds(structureLayer))
            {
                object structureFeature = InvokeFeatureMethod(
                    structureLayer,
                    "Feature",
                    structureFid
                );
                MethodInfo addFeature = breaklineLayer.GetType().GetMethods()
                    .Where(method =>
                        method.Name == "AddFeature" &&
                        method.GetParameters().Length == 1 &&
                        method.GetParameters()[0].ParameterType.IsAssignableFrom(
                            structureFeature.GetType()
                        )
                    )
                    .First();
                addFeature.Invoke(
                    breaklineLayer,
                    new object[] { structureFeature }
                );
                int newFid = FeatureIds(breaklineLayer).Count - 1;
                temporaryBreaklineFids.Add(newFid);
                object structureRow = InvokeFeatureMethod(
                    structureLayer,
                    "FeatureRow",
                    structureFid
                );
                object breaklineRow = InvokeFeatureMethod(
                    breaklineLayer,
                    "FeatureRow",
                    newFid
                );
                foreach (string column in spacingColumns)
                    SetRowValue(
                        breaklineRow,
                        column,
                        RowValue(structureRow, column)
                    );
            }
            temporaryStructureBreaklines = temporaryBreaklineFids.Count;

            Type generatorType = _assembly.GetType(
                "RasMapperLib.EditLayers.PointGenerator",
                true
            );
            MethodInfo regenerate = generatorType.GetMethods(
                BindingFlags.Public | BindingFlags.NonPublic |
                BindingFlags.Static | BindingFlags.Instance
            ).Single(method =>
                method.Name == "RegenerateMeshPoints" &&
                method.GetParameters().Length == 7 &&
                method.GetParameters()[0].ParameterType != geometryType &&
                !method.IsStatic
            );
            persistence.RegenerateParameterSignature = string.Join(
                "|",
                regenerate.GetParameters().Select(parameter =>
                    parameter.Position.ToString(CultureInfo.InvariantCulture) +
                    ":" + parameter.Name + ":" +
                    parameter.ParameterType.FullName
                ).ToArray()
            );
            object generator = Activator.CreateInstance(
                generatorType,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
                null,
                new object[] { geometry },
                null
            );
            List<int> activeBreaklines = FeatureIds(breaklineLayer);
            object meshRegions = Property(geometry, "MeshRegions");
            refinementRegions = RefinementRegions(meshRegions);
            List<int> activeRegions = FeatureIds(meshRegions);
            // Match RAS Mapper's selected-area regeneration contract: both
            // activePerims and regeneratePerims contain the target flow-area
            // FID. The geometry-wide MeshPoints table remains indexed by FID,
            // and only that row is consumed and persisted below.
            List<int> activePerimeters = new List<int> { fid };
            List<int> regeneratePerimeters = new List<int> { fid };
            object meshPointsLayer = Property(geometry, "MeshPoints");
            if (DisableFileSystemWatcher(meshPointsLayer))
                fileSystemWatchersDisabled++;
            object meshPoints = null;
            try
            {
                if (seedGenerationMode == "point_generator")
                {
                    if (requestedCellSize <= 0.0)
                        throw new InvalidOperationException(
                            "The managed mesh host needs a positive CELL_SIZE " +
                            "for point_generator seed generation"
                        );
                    meshPoints = GenerateFallbackSeeds(
                        perimeter,
                        requestedCellSize,
                        generatorType
                    );
                    seedCount = PointCount(meshPoints);
                    persistence.SeedGenerationMethod = "point_generator";
                    persistence.SeedFallbackUsed = false;
                    persistence.SeedFallbackCellSize = requestedCellSize;
                    Stage("seeds-point-generator-generated");
                }
                else
                {
                    regenerate.Invoke(
                        generator,
                        new object[] {
                            activeBreaklines,
                            activeRegions,
                            activePerimeters,
                            regeneratePerimeters,
                            null,
                            null,
                            false
                        }
                    );
                    Stage("seeds-regenerated");
                    meshPoints = meshPointsLayer.GetType()
                        .GetProperty("Item")
                        .GetValue(meshPointsLayer, new object[] { fid });
                    seedCount = Convert.ToInt32(
                        meshPoints.GetType()
                            .GetMethod("PointMCount")
                            .Invoke(meshPoints, null)
                    );
                    if (seedCount == 0)
                    {
                        double fallbackCellSize = requestedCellSize;
                        if (fallbackCellSize <= 0.0)
                            throw new InvalidOperationException(
                                "The managed mesh host needs a positive CELL_SIZE " +
                                "when RegenerateMeshPoints returns no seeds"
                            );
                        meshPoints = GenerateFallbackSeeds(
                            perimeter,
                            fallbackCellSize,
                            generatorType
                        );
                        seedCount = PointCount(meshPoints);
                        persistence.SeedGenerationMethod =
                            "regenerate_then_generate_points_fallback";
                        persistence.SeedFallbackUsed = true;
                        persistence.SeedFallbackCellSize = fallbackCellSize;
                        Stage("seeds-fallback-generated");
                    }
                }
            }
            finally
            {
                foreach (int temporaryFid in temporaryBreaklineFids
                    .OrderByDescending(value => value))
                    InvokeFeatureMethod(
                        breaklineLayer,
                        "DeleteFeature",
                        temporaryFid
                    );
            }

            MethodInfo setMeshPointsFeature = meshPointsLayer.GetType()
                .GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .Where(method =>
                    method.Name == "SetFeature" &&
                    method.GetParameters().Length == 2 &&
                    method.GetParameters()[0].ParameterType == typeof(int)
                )
                .First();
            object meshPointsFeature = meshPoints;
            if (!setMeshPointsFeature.GetParameters()[1].ParameterType
                .IsAssignableFrom(meshPoints.GetType()))
            {
                Type multiPointType = _assembly.GetType(
                    "RasMapperLib.MultiPoint",
                    true
                );
                ConstructorInfo multiPointConstructor = multiPointType
                    .GetConstructors(BindingFlags.Public | BindingFlags.Instance)
                    .Where(constructor =>
                        constructor.GetParameters().Length == 1 &&
                        constructor.GetParameters()[0].ParameterType
                            .IsAssignableFrom(meshPoints.GetType())
                    )
                    .First();
                meshPointsFeature = multiPointConstructor.Invoke(
                    new object[] { meshPoints }
                );
            }
            object setMeshPointsResult = setMeshPointsFeature.Invoke(
                meshPointsLayer,
                new object[] { fid, meshPointsFeature }
            );
            System.Data.DataRow meshPointsRow =
                setMeshPointsResult as System.Data.DataRow;
            string meshPointsColumnName = Convert.ToString(
                Property(meshPointsLayer, "FeatureColumnName"),
                CultureInfo.InvariantCulture
            );
            persistence.MeshPointsSetFeatureReturnedDataRow =
                meshPointsRow != null;
            if (
                meshPointsRow == null ||
                String.IsNullOrEmpty(meshPointsColumnName) ||
                !meshPointsRow.Table.Columns.Contains(meshPointsColumnName) ||
                !Object.ReferenceEquals(
                    meshPointsRow[meshPointsColumnName],
                    meshPointsFeature
                )
            )
                throw new IOException(
                    "MeshPointLayer.SetFeature did not retain the generated " +
                    "seed points for FID " +
                    fid.ToString(CultureInfo.InvariantCulture)
                );
            persistence.MeshPointsSetFeatureRowReferenceMatchesGenerated = true;
            Stage("mesh-points-feature-row-reference-matched");

            Type polylineType = _assembly.GetType(
                "RasMapperLib.Polyline",
                true
            );
            Type polylineLayerType = _assembly.GetType(
                "RasMapperLib.PolylineFeatureLayer",
                true
            );
            object combinedLayer = Activator.CreateInstance(
                polylineLayerType,
                new object[] { "ras-commander mesh constraints" }
            );
            constraintCount += AddPolylineFeatures(
                Property(layerGeometry, "BreakLines"),
                "Polylines",
                combinedLayer,
                polylineType
            );
            constraintCount += AddPolylineFeatures(
                Property(layerGeometry, "MeshRegions"),
                "Polygons",
                combinedLayer,
                polylineType
            );
            constraintCount += AddPolylineFeatures(
                Property(layerGeometry, "Structures"),
                "Polylines",
                combinedLayer,
                polylineType
            );
            object constraints = constraintCount == 0
                ? null
                : combinedLayer.GetType()
                    .GetMethod("CopyToMultiPartPolyline")
                    .Invoke(combinedLayer, null);

            Type polygonType = _assembly.GetType(
                "RasMapperLib.Polygon",
                true
            );
            Type meshType = _assembly.GetType("RasMapperLib.MeshFV2D", true);
            ConstructorInfo meshConstructor = meshType.GetConstructors(
                BindingFlags.Public | BindingFlags.NonPublic |
                BindingFlags.Instance
            ).Single(constructor =>
                constructor.GetParameters().Length == 5 &&
                constructor.GetParameters()[0].ParameterType == polygonType &&
                constructor.GetParameters()[4].ParameterType == typeof(double)
            );
            object mesh = null;
            object currentMeshPoints = meshPoints;
            for (int meshAttempt = 0; meshAttempt < 6; meshAttempt++)
            {
                persistence.MeshIterations = meshAttempt + 1;
                mesh = meshConstructor.Invoke(
                    new object[] {
                        perimeter,
                        currentMeshPoints,
                        constraints,
                        null,
                        minFaceLengthRatio
                    }
                );
                meshState = Property(mesh, "MeshCompletionState").ToString();
                cellCount = Convert.ToInt32(
                    Property(mesh, "NonVirtualCellCount")
                );
                faceCount = Convert.ToInt32(Property(mesh, "FaceCount"));
                if (meshState == "Complete")
                    break;
                if (
                    meshState != "MaxFacesPerCellExceeded" ||
                    meshAttempt >= 5
                )
                    break;

                int addedMidpoints;
                object repairedMeshPoints = AddMaxFaceMidpointSeeds(
                    mesh,
                    currentMeshPoints,
                    out addedMidpoints
                );
                if (addedMidpoints <= 0)
                    break;
                currentMeshPoints = repairedMeshPoints;
                string fix = "MaxFaces:midpoints(+" +
                    addedMidpoints.ToString(CultureInfo.InvariantCulture) +
                    "pts)";
                persistence.FixesApplied.Add(fix);
                Stage("max-faces-midpoints-added-" +
                    addedMidpoints.ToString(CultureInfo.InvariantCulture));
            }
            if (meshState != "Complete")
                throw new InvalidOperationException(
                    "MeshFV2D did not complete: " + meshState
                );

            if (!Object.ReferenceEquals(currentMeshPoints, meshPoints))
            {
                meshPoints = currentMeshPoints;
                seedCount = PointCount(meshPoints);
                object repairedMeshPointsFeature = meshPoints;
                if (!setMeshPointsFeature.GetParameters()[1].ParameterType
                    .IsAssignableFrom(meshPoints.GetType()))
                {
                    Type multiPointType = _assembly.GetType(
                        "RasMapperLib.MultiPoint",
                        true
                    );
                    ConstructorInfo multiPointConstructor = multiPointType
                        .GetConstructors(
                            BindingFlags.Public | BindingFlags.Instance
                        )
                        .Where(constructor =>
                            constructor.GetParameters().Length == 1 &&
                            constructor.GetParameters()[0].ParameterType
                                .IsAssignableFrom(meshPoints.GetType())
                        )
                        .First();
                    repairedMeshPointsFeature = multiPointConstructor.Invoke(
                        new object[] { meshPoints }
                    );
                }
                object repairedResult = setMeshPointsFeature.Invoke(
                    meshPointsLayer,
                    new object[] { fid, repairedMeshPointsFeature }
                );
                System.Data.DataRow repairedRow =
                    repairedResult as System.Data.DataRow;
                if (
                    repairedRow == null ||
                    String.IsNullOrEmpty(meshPointsColumnName) ||
                    !repairedRow.Table.Columns.Contains(meshPointsColumnName) ||
                    !Object.ReferenceEquals(
                        repairedRow[meshPointsColumnName],
                        repairedMeshPointsFeature
                    )
                )
                    throw new IOException(
                        "MeshPointLayer.SetFeature did not retain repaired " +
                        "max-faces seed points for FID " +
                        fid.ToString(CultureInfo.InvariantCulture)
                    );
                persistence.MeshPointsSetFeatureReturnedDataRow = true;
                persistence.MeshPointsSetFeatureRowReferenceMatchesGenerated =
                    true;
                Stage("mesh-points-max-faces-repair-retained");
            }
            Stage("mesh-complete");

            cellCenters = ExtractCellCenters(mesh, meshType, cellCount);
            Stage("cell-centers-extracted");

            if (hdfSaveRequested)
            {
                ReloadSuppressorHandle reloadSuppressor = null;
                try
                {
                    if (persistenceMode == "transactional_direct")
                        reloadSuppressor = CreateReloadSuppressor(
                            d2FlowArea,
                            persistence
                        );

                    MethodInfo setFeature = d2FlowArea.GetType().GetMethods()
                        .Where(method =>
                            method.Name == "SetFeature" &&
                            method.GetParameters().Length == 2 &&
                            method.GetParameters()[0].ParameterType == typeof(int) &&
                            method.GetParameters()[1].ParameterType.IsAssignableFrom(
                                meshType
                            )
                        )
                        .First();
                    object setFeatureResult = setFeature.Invoke(
                        d2FlowArea,
                        new object[] { fid, mesh }
                    );
                    System.Data.DataRow updatedRow =
                        setFeatureResult as System.Data.DataRow;
                    persistence.SetFeatureReturnedDataRow = updatedRow != null;
                    persistence.SetFeatureColumnName = Convert.ToString(
                        Property(d2FlowArea, "FeatureColumnName"),
                        CultureInfo.InvariantCulture
                    );
                    if (
                        updatedRow == null ||
                        String.IsNullOrEmpty(persistence.SetFeatureColumnName) ||
                        !updatedRow.Table.Columns.Contains(
                            persistence.SetFeatureColumnName
                        ) ||
                        !Object.ReferenceEquals(
                            updatedRow[persistence.SetFeatureColumnName],
                            mesh
                        )
                    )
                        throw new IOException(
                            "RASD2FlowArea.SetFeature did not retain the " +
                            "generated mesh in its returned DataRow"
                        );
                    persistence.SetFeatureRowReferenceMatchesGenerated = true;
                    Stage("set-feature-row-reference-matched");

                    d2FlowArea.GetType()
                        .GetMethod(
                            "SetMeshHasBeenRecomputed",
                            new[] { typeof(int), typeof(bool) }
                        )
                        .Invoke(d2FlowArea, new object[] { fid, true });
                    d2FlowArea.GetType()
                        .GetMethod(
                            "SetMeshUpToDate",
                            new[] { typeof(int), typeof(bool) }
                        )
                        .Invoke(d2FlowArea, new object[] { fid, true });
                    if (persistenceMode == "transactional_direct")
                    {
                        WriteMeshDirectly(
                            geometry,
                            d2FlowArea,
                            perimeters,
                            mesh,
                            meshType,
                            hdfPath,
                            meshName,
                            fid,
                            cellCount,
                            faceCount,
                            cellCenters,
                            true,
                            receiptPath,
                            meshState,
                            seedCount,
                            constraintCount,
                            temporaryStructureBreaklines,
                            fileSystemWatchersDisabled,
                            refinementRegions,
                            reloadSuppressor,
                            persistence
                        );
                    }
                    else
                    {
                        MethodInfo save = d2FlowArea.GetType().GetMethods()
                            .First(method =>
                                method.Name == "Save" &&
                                method.GetParameters().Length == 0
                            );
                        object saveResult = save.Invoke(d2FlowArea, null);
                        if (saveResult is bool && !(bool)saveResult)
                            throw new IOException(
                                "RASD2FlowArea.Save reported failure for " +
                                meshName
                            );
                    }
                    meshSaved = true;
                    Stage("mesh-saved");
                }
                finally
                {
                    if (
                        reloadSuppressor != null &&
                        !reloadSuppressor.IsDisposed
                    )
                    {
                        reloadSuppressor.Dispose();
                        persistence.ReloadSuppressorDisposed = true;
                        Stage("feature-table-reload-suppressor-disposed-on-exit");
                    }
                }
            }
            else
            {
                Stage("hdf-save-skipped");
            }

            WriteReceipt(
                receiptPath,
                "complete",
                meshState,
                seedCount,
                cellCount,
                faceCount,
                constraintCount,
                temporaryStructureBreaklines,
                fileSystemWatchersDisabled,
                refinementRegions,
                cellCenters,
                hdfSaveRequested,
                meshSaved,
                persistence,
                ""
            );
            return 0;
        }
        catch (Exception exception)
        {
            Exception error = Unwrap(exception);
            string detail = error.GetType().FullName + ": " + error.Message;
            try
            {
                WriteReceipt(
                    receiptPath,
                    "error",
                    meshState,
                    seedCount,
                    cellCount,
                    faceCount,
                    constraintCount,
                    temporaryStructureBreaklines,
                    fileSystemWatchersDisabled,
                    refinementRegions,
                    cellCenters,
                    hdfSaveRequested,
                    meshSaved,
                    persistence,
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
