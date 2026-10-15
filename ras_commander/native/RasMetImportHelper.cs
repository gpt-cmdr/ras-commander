// Original interop wrapper: raster decoding and HDF writing run in HEC's assemblies.
using System;
using System.Collections.Generic;
using System.IO;
using System.Globalization;
using System.Text.RegularExpressions;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;

internal static class RasMetImportHelper
{
    static string install;
    static readonly List<Assembly> assemblies = new List<Assembly>();
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)]
    static extern bool SetDllDirectory(string directory);
    static Assembly Resolve(object sender, ResolveEventArgs args) {
        string path=Path.Combine(install,new AssemblyName(args.Name).Name+".dll");
        return File.Exists(path)?Assembly.LoadFrom(path):null;
    }
    static Type TypeOf(string name) {
        foreach(Assembly asm in assemblies) { Type t=asm.GetType(name,false); if(t!=null)return t; }
        throw new MissingMemberException("Native type unavailable: "+name);
    }
    static MethodInfo Method(Type type, string name, int count, bool generic) {
        MethodInfo[] matches=type.GetMethods().Where(m=>m.Name==name && m.GetParameters().Length==count && m.IsGenericMethodDefinition==generic).ToArray();
        if(matches.Length!=1)throw new MissingMethodException("Ambiguous/changed native contract: "+type.FullName+"."+name);
        return matches[0];
    }
    static object Call(Type type, string name, object target, params object[] args) {
        return Method(type,name,args.Length,false).Invoke(target,args);
    }
    static string UnitKey(string unit) {
        string s=(unit??"").Trim().ToLowerInvariant();
        if(new[]{"mm/hr","mmph","millimeterperhour"}.Contains(s))return "mm/hr";
        if(new[]{"in/hr","iph","inchesperhour","inches/hour"}.Contains(s))return "in/hr";
        if(new[]{"mm","millimeter","millimeters","kg/m^2","[kg/m^2]","[kg/(m^2)]"}.Contains(s))return "mm";
        if(new[]{"in","inch","inches"}.Contains(s))return "in";
        return s;
    }
    static int Main(string[] args) {
        var json=new JavaScriptSerializer();
        var result=new Dictionary<string,object>();
        string response=args.Length==3?args[2]:null;
        IDisposable raster=null, writer=null;
        try {
            if(args.Length!=3)throw new ArgumentException("Expected install, request.json, response.json");
            install=Path.GetFullPath(args[0]);
            AppDomain.CurrentDomain.AssemblyResolve+=Resolve;
            SetDllDirectory(Path.Combine(install,"bin64"));
            Environment.SetEnvironmentVariable("PATH",Path.Combine(install,"bin64")+";"+Path.Combine(install,"GDAL","bin64")+";"+install+";"+Environment.GetEnvironmentVariable("PATH"));
            foreach(string name in new[]{"Geospatial.Core.dll","Geospatial.GDALAssist.dll","Geospatial.IO.dll","H5Assist.dll","Utility.Core.dll","Utility.Units.dll","Utility.Progress.dll"}) {
                string path=Path.Combine(install,name); if(File.Exists(path))assemblies.Add(Assembly.LoadFrom(path));
            }
            var request=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(args[1]));
            string source=(string)request["source"], selector=(string)request["dataset"], output=(string)request["output"], units=(string)request["units"], dataType=(string)request["data_type"];
            if(!File.Exists(source))throw new FileNotFoundException("Source raster missing",source);
            if(!new[]{"cumulative","per-avg","per-aver"}.Contains(dataType))throw new ArgumentException("Only cumulative and period-average source semantics are implemented");
            if(!new[]{".nc",".nc4",".netcdf"}.Contains(Path.GetExtension(source).ToLowerInvariant()))throw new ArgumentException("Native helper supports NetCDF only");
            string group="/Event Conditions/Meteorology/Precipitation/Imported Raster Data/Values";
            Type setup=TypeOf("Geospatial.GDALAssist.GDALSetup");
            Call(setup,"Initialize",null,Path.Combine(install,"GDAL","bin64"),Path.Combine(install,"GDAL","common","data"),Path.Combine(install,"GDAL","bin64","gdalplugins"),Path.Combine(install,"GDAL","common","WMS"));
            Call(setup,"EnsureInitialized",null);
            Type rasterType=TypeOf("Geospatial.GDALAssist.GDALRaster");
            string connection="NETCDF:\""+source+"\":"+selector;
            object native=Activator.CreateInstance(rasterType,new object[]{connection}); raster=(IDisposable)native;
            // Read CF metadata through vendor GDAL. Its convenience timestamp
            // parser indexes a missing time token for date-only epochs and
            // accepts only Int64 offsets. This adapter handles valid CF decimal
            // offsets/scientific notation without rewriting or decoding NetCDF
            // in Python. Raster values still come exclusively from vendor GDAL.
            string timeUnits=(string)Call(rasterType,"GetMetadataItem",native,"time#units","");
            string calendar=(string)Call(rasterType,"GetMetadataItem",native,"time#calendar","");
            if(!String.IsNullOrWhiteSpace(calendar) && !new[]{"standard","gregorian","proleptic_gregorian"}.Contains(calendar.Trim().Trim('{','}','"').ToLowerInvariant()))throw new InvalidDataException("Unsupported CF calendar: "+calendar);
            Match cf=Regex.Match((timeUnits??"").Trim().Trim('{','}','\"'),@"^(seconds?|minutes?|hours?|days?)\s+since\s+(.+)$",RegexOptions.IgnoreCase);
            if(!cf.Success)throw new InvalidDataException("Unsupported CF time units: "+timeUnits);
            DateTimeOffset origin;
            if(!DateTimeOffset.TryParse(cf.Groups[2].Value.Trim(),CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal,out origin))throw new InvalidDataException("Invalid CF time epoch: "+timeUnits);
            double scale=cf.Groups[1].Value.ToLowerInvariant().StartsWith("second")?1:cf.Groups[1].Value.ToLowerInvariant().StartsWith("minute")?60:cf.Groups[1].Value.ToLowerInvariant().StartsWith("hour")?3600:86400;
            string[] offsets=(string[])Call(rasterType,"GetMetadataItemsFromEachBand",native,"NETCDF_DIM_time","");
            int bands=(int)Call(rasterType,"GetBandCount",native);
            if(offsets==null || offsets.Length!=bands || bands<2)throw new InvalidDataException("Vendor GDAL did not expose time offsets for at least two raster bands");
            DateTime[] times=new DateTime[bands];
            for(int i=0;i<bands;i++) {
                double offset;
                if(!Double.TryParse(offsets[i],NumberStyles.Float,CultureInfo.InvariantCulture,out offset) || Double.IsNaN(offset) || Double.IsInfinity(offset))throw new InvalidDataException("Invalid CF band time offset: "+offsets[i]);
                times[i]=DateTime.SpecifyKind(origin.UtcDateTime.AddSeconds(offset*scale),DateTimeKind.Unspecified);
                if(times[i].Ticks%TimeSpan.TicksPerSecond!=0)throw new InvalidDataException("Native precipitation timestamps must be whole seconds");
                if(i>0 && times[i]<=times[i-1])throw new InvalidDataException("Vendor GDAL timestamps must be strictly increasing");
            }
            string declared=(string)Call(rasterType,"TryParseUnits",native);
            if(!String.IsNullOrWhiteSpace(declared) && UnitKey(declared)!=UnitKey(units))throw new InvalidDataException("Source units "+declared+" conflict with requested units "+units);
            object projection=Call(rasterType,"GetProjection",native);
            string wkt=projection==null?null:(string)Call(projection.GetType(),"GetWKT",projection);
            if(String.IsNullOrWhiteSpace(wkt))throw new InvalidDataException("Vendor GDAL did not read a source CRS");
            Type bandType=TypeOf("Geospatial.GDALAssist.GdalBandedRaster`1").MakeGenericType(typeof(float));
            object banded=Activator.CreateInstance(bandType,new object[]{native});
            object series=Method(TypeOf("Geospatial.Rasters.IBandedRasterExtensions"),"AsTimeSeriesRaster",2,true).MakeGenericMethod(typeof(float)).Invoke(null,new object[]{banded,times});
            Type progressType=TypeOf("Utility.Progress.ProgressReporter");
            object progress=Call(progressType,"ConsoleWrite",null);
            Type writerType=TypeOf("H5Assist.H5Writer");
            object hw=Activator.CreateInstance(writerType,new object[]{output}); writer=(IDisposable)hw;
            Type rasterWriter=TypeOf("Geospatial.IO.H5RasterWriter");
            Type timeSeriesType=TypeOf("Geospatial.PairedData.TimeSeriesDataType");
            object amount=Enum.Parse(timeSeriesType,"Amount");
            object sourceType=Enum.Parse(timeSeriesType,dataType=="cumulative"?"Amount":dataType=="per-cum"?"Delta":"Rate");
            object interpolation=Enum.Parse(TypeOf("Geospatial.PairedData.InterpolationMethod"),dataType=="per-avg"||dataType=="per-aver"?"ApplyPointToPreviousSegment":"Linear");
            if(dataType!="cumulative") {
                float[] first=(float[])Method(TypeOf("Geospatial.Rasters.IBandedRasterExtensions"),"GetProfile",2,true).MakeGenericMethod(typeof(float)).Invoke(null,new object[]{banded,0});
                if(first.Any(v=>!Single.IsNaN(v)&&Math.Abs(v)>1e-6))throw new InvalidDataException("Native rate/interval inputs require a zero first baseline frame; nonzero first-interval duration is not implemented");
            }
            object hour=TypeOf("Utility.Units.Time").GetField("Hours").GetValue(null);
            object accumulator=Activator.CreateInstance(TypeOf("Geospatial.Rasters.TimeSeriesRasterAccumulatorF"),new object[]{series,sourceType,hour,interpolation});
            MethodInfo writeAccumulated=rasterWriter.GetMethods().Single(m=>m.Name=="WriteAccumulatedRaster" && m.IsGenericMethodDefinition && m.GetParameters()[0].ParameterType==writerType).MakeGenericMethod(typeof(float));
            writeAccumulated.Invoke(null,new object[]{hw,group,accumulator,amount,(float?)-9999f,progress});
            MethodInfo attr=writerType.GetMethods().Single(m=>m.Name=="WriteAttribute" && m.IsGenericMethodDefinition && m.GetParameters().Length==3 && m.GetParameters()[2].ParameterType.IsGenericParameter).MakeGenericMethod(typeof(string));
            string outputUnits=UnitKey(units).Replace("/hr","");
            attr.Invoke(hw,new object[]{group,"Units",outputUnits});
            attr.Invoke(hw,new object[]{group,"Data Type","cumulative"});
            attr.Invoke(hw,new object[]{group,"Projection",wkt});
            MethodInfo optimize=rasterWriter.GetMethods().Single(m=>m.Name=="OptimizeForVerticalReading" && m.IsGenericMethodDefinition && m.GetParameters()[0].ParameterType==writerType).MakeGenericMethod(typeof(float));
            optimize.Invoke(null,new object[]{hw,group,progress});
            result["success"]=true; result["bands"]=bands; result["timestamp_parser"]="vendor-gdal-cf-metadata-v1"; result["time_units"]=timeUnits;
            result["times"]=times.Select(t=>t.ToString("yyyy-MM-ddTHH:mm:ss")).ToArray();
            result["declared_units"]=declared; result["units"]=outputUnits; result["data_type"]="cumulative"; result["source_data_type"]=dataType;
            result["gdal_assembly"]=rasterType.Assembly.Location;
            result["gdal_assembly_version"]=rasterType.Assembly.GetName().Version.ToString();
            result["source"]=source; result["dataset"]=selector;
        } catch(Exception error) {
            while(error is TargetInvocationException && error.InnerException!=null)error=error.InnerException;
            result["success"]=false; result["error"]=error.ToString(); Console.Error.WriteLine(error);
        } finally {
            if(writer!=null)writer.Dispose(); if(raster!=null)raster.Dispose();
        }
        if(response!=null)File.WriteAllText(response,json.Serialize(result));
        return result.ContainsKey("success") && (bool)result["success"]?0:1;
    }
}
