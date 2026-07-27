using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using TiffAssist;

internal static class Program
{
	private static int Main(string[] args)
	{
		if (args.Length < 4 || args.Length > 6)
		{
			Console.Error.WriteLine(
				"Usage: TiffAssistExperimentHarness.exe OUTPUT WIDTH HEIGHT REPEATS [NODATA_TILE_INTERVAL] [TEMPLATE_TILE_COUNT]"
			);
			return 2;
		}

		string output = Path.GetFullPath(args[0]);
		int width = int.Parse(args[1], CultureInfo.InvariantCulture);
		int height = int.Parse(args[2], CultureInfo.InvariantCulture);
		int repeats = int.Parse(args[3], CultureInfo.InvariantCulture);
		int noDataTileInterval = args.Length == 5
			? int.Parse(args[4], CultureInfo.InvariantCulture)
			: args.Length == 6
			? int.Parse(args[4], CultureInfo.InvariantCulture)
			: 0;
		int templateTileCount = args.Length == 6
			? int.Parse(args[5], CultureInfo.InvariantCulture)
			: 0;
		if (width < 1 || height < 1 || repeats < 1 ||
			noDataTileInterval < 0 || templateTileCount < 0)
		{
			throw new ArgumentOutOfRangeException("Dimensions and repeats must be positive.");
		}
		Directory.CreateDirectory(Path.GetDirectoryName(output));

		int gen0Before = GC.CollectionCount(0);
		int gen1Before = GC.CollectionCount(1);
		int gen2Before = GC.CollectionCount(2);
		long memoryBefore = GC.GetTotalMemory(true);
		Stopwatch stopwatch = Stopwatch.StartNew();
		for (int repeat = 0; repeat < repeats; repeat++)
		{
			string repeatOutput = repeats == 1
				? output
				: Path.Combine(
					Path.GetDirectoryName(output),
					Path.GetFileNameWithoutExtension(output) + "-" + repeat + Path.GetExtension(output)
				);
			WriteRaster(
				repeatOutput,
				width,
				height,
				noDataTileInterval,
				templateTileCount);
		}
		stopwatch.Stop();
		long memoryAfter = GC.GetTotalMemory(false);

		Console.WriteLine(string.Format(
			CultureInfo.InvariantCulture,
			"{{\"schema\":\"ras-commander.tiff-harness/1\",\"elapsed_seconds\":{0:F6}," +
			"\"width\":{1},\"height\":{2},\"repeats\":{3},\"nodata_tile_interval\":{4}," +
			"\"template_tile_count\":{5},\"managed_bytes_before\":{6},\"managed_bytes_after\":{7}," +
			"\"gen0_collections\":{8},\"gen1_collections\":{9},\"gen2_collections\":{10}}}",
			stopwatch.Elapsed.TotalSeconds,
			width,
			height,
			repeats,
			noDataTileInterval,
			templateTileCount,
			memoryBefore,
			memoryAfter,
			GC.CollectionCount(0) - gen0Before,
			GC.CollectionCount(1) - gen1Before,
			GC.CollectionCount(2) - gen2Before
		));
		return 0;
	}

	private static void WriteRaster(
		string output,
		int width,
		int height,
		int noDataTileInterval,
		int templateTileCount)
	{
		const float noData = -9999.0f;
		TiffMetadata<float> metadata = new TiffMetadata<float>(noData, RoundTo.Sixteenths);
		metadata.Artist = "HEC-RAS";
		metadata.Software = "ras-commander copied-assembly experiment";
		metadata.DataType = "Depth";
		metadata.DataUnits = "ft";
		metadata.ImageDescription = "Deterministic TiffAssist experiment fixture";

		using (FloatTiffWriter writer = new FloatTiffWriter(
			output, width, height, true, metadata, "8", true))
		{
			int tilesWide = (width + metadata.TileWidth - 1) / metadata.TileWidth;
			int tilesTall = (height + metadata.TileHeight - 1) / metadata.TileHeight;
			float[] tile = new float[metadata.TileWidth * metadata.TileHeight];
			float[][] templates = BuildTemplates(
				templateTileCount,
				tilesWide,
				tilesTall,
				width,
				height,
				metadata,
				noData);
			byte[] rawNoData = null;
			List<int> noDataTiles = new List<int>();
			if (noDataTileInterval > 0)
			{
				float[] noDataTile = new float[tile.Length];
				for (int index = 0; index < noDataTile.Length; index++)
				{
					noDataTile[index] = noData;
				}
				byte[] noDataBytes = new byte[noDataTile.Length * sizeof(float)];
				Buffer.BlockCopy(noDataTile, 0, noDataBytes, 0, noDataBytes.Length);
				rawNoData = writer.GetRawTile(0, noDataBytes);
			}
			for (int tileRow = 0; tileRow < tilesTall; tileRow++)
			{
				for (int tileColumn = 0; tileColumn < tilesWide; tileColumn++)
				{
					int tileNumber = tileRow * tilesWide + tileColumn;
					if (noDataTileInterval > 0 && tileNumber % noDataTileInterval == noDataTileInterval - 1)
					{
						noDataTiles.Add(tileNumber);
						continue;
					}
					if (templates == null)
					{
						FillTile(tile, tileRow, tileColumn, width, height, metadata, noData);
						writer.WriteTile(tileNumber, tile);
					}
					else
					{
						writer.WriteTile(tileNumber, templates[tileNumber % templates.Length]);
					}
				}
			}
			foreach (int tileNumber in noDataTiles)
			{
				writer.WriteRawTile(tileNumber, rawNoData);
			}
		}
	}

	private static float[][] BuildTemplates(
		int requested,
		int tilesWide,
		int tilesTall,
		int width,
		int height,
		TiffMetadata<float> metadata,
		float noData)
	{
		if (requested == 0)
		{
			return null;
		}
		int count = Math.Min(requested, tilesWide * tilesTall);
		float[][] templates = new float[count][];
		for (int index = 0; index < count; index++)
		{
			templates[index] = new float[metadata.TileWidth * metadata.TileHeight];
			int tileRow = index / tilesWide;
			int tileColumn = index % tilesWide;
			FillTile(
				templates[index],
				tileRow,
				tileColumn,
				width,
				height,
				metadata,
				noData);
		}
		return templates;
	}

	private static void FillTile(
		float[] tile,
		int tileRow,
		int tileColumn,
		int width,
		int height,
		TiffMetadata<float> metadata,
		float noData)
	{
		for (int row = 0; row < metadata.TileHeight; row++)
		{
			int y = tileRow * metadata.TileHeight + row;
			for (int column = 0; column < metadata.TileWidth; column++)
			{
				int x = tileColumn * metadata.TileWidth + column;
				int index = row * metadata.TileWidth + column;
				if (x >= width || y >= height || ((x * 17 + y * 31) % 97 == 0))
				{
					tile[index] = noData;
				}
				else
				{
					tile[index] = (float)(
						Math.Sin(x * 0.0041) * 8.0 +
						Math.Cos(y * 0.0037) * 5.0 +
						(x % 41) * 0.017 +
						(y % 29) * 0.011
					);
				}
			}
		}
	}
}
