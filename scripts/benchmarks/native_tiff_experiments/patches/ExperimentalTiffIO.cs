using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using BitMiracle.LibTiff.Classic;
using Stats = Utility.Stats;

namespace TiffAssist;

/// <summary>
/// Opt-in settings for the copied TiffAssist experiment. The patched assembly
/// behaves like the original unless RASCOMMANDER_TIFF_EXPERIMENT is true.
/// </summary>
internal static class ExperimentalTiffSettings
{
	private const int MinimumBatchBytes = 64 * 1024;
	private const int MaximumBatchBytes = 64 * 1024 * 1024;

	internal static bool Enabled => ReadBoolean("RASCOMMANDER_TIFF_EXPERIMENT", false);

	internal static int BatchBytes
	{
		get
		{
			int value = ReadInteger("RASCOMMANDER_TIFF_BATCH_BYTES", 256 * 1024);
			if (value < MinimumBatchBytes || value > MaximumBatchBytes)
			{
				throw new ArgumentOutOfRangeException(
					"RASCOMMANDER_TIFF_BATCH_BYTES",
					value,
					"Experimental TIFF batches must be between 65536 and 67108864 bytes."
				);
			}
			return value;
		}
	}

	internal static bool ReuseTileBuffer =>
		Enabled && ReadBoolean("RASCOMMANDER_TIFF_REUSE_BUFFER", true);

	internal static string StatisticsMode
	{
		get
		{
			if (!Enabled)
			{
				return "native";
			}
			string value = (Environment.GetEnvironmentVariable(
				"RASCOMMANDER_TIFF_STATS_MODE") ?? "serial").Trim().ToLowerInvariant();
			if (value != "native" && value != "serial" && value != "none")
			{
				throw new ArgumentException(
					"RASCOMMANDER_TIFF_STATS_MODE must be native, serial, or none."
				);
			}
			return value;
		}
	}

	internal static bool UseSerialStatistics => StatisticsMode == "serial";

	internal static bool ApplyTrackStats(bool requested) =>
		requested && StatisticsMode != "none";

	internal static bool WriteProfile =>
		Enabled && ReadBoolean("RASCOMMANDER_TIFF_WRITE_PROFILE", true);

	internal static int PipelineWorkers
	{
		get
		{
			if (!Enabled)
			{
				return 0;
			}
			int value = ReadInteger("RASCOMMANDER_TIFF_PIPELINE_WORKERS", 0);
			if (value < 0 || value > 32)
			{
				throw new ArgumentOutOfRangeException(
					"RASCOMMANDER_TIFF_PIPELINE_WORKERS",
					value,
					"Experimental TIFF pipeline workers must be between 0 and 32."
				);
			}
			return value;
		}
	}

	internal static int PipelineQueueDepth
	{
		get
		{
			// Raw commits are much faster than tile preparation/compression. A small
			// bound keeps the workers fed without retaining dozens of full tile
			// snapshots and compressed buffers under large-watershed pressure.
			int fallback = 2;
			int value = ReadInteger("RASCOMMANDER_TIFF_PIPELINE_QUEUE_DEPTH", fallback);
			if (value < 1 || value > 128)
			{
				throw new ArgumentOutOfRangeException(
					"RASCOMMANDER_TIFF_PIPELINE_QUEUE_DEPTH",
					value,
					"Experimental TIFF pipeline queue depth must be between 1 and 128."
				);
			}
			return value;
		}
	}

	internal static bool PipelineEnabled => PipelineWorkers > 0;

	private static bool ReadBoolean(string name, bool fallback)
	{
		string value = Environment.GetEnvironmentVariable(name);
		if (string.IsNullOrWhiteSpace(value))
		{
			return fallback;
		}
		value = value.Trim().ToLowerInvariant();
		return value == "1" || value == "true" || value == "yes" || value == "on";
	}

	private static int ReadInteger(string name, int fallback)
	{
		string value = Environment.GetEnvironmentVariable(name);
		int parsed;
		return int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out parsed)
			? parsed
			: fallback;
	}
}

/// <summary>
/// Thread-safe counters shared by the tile pipeline and the final TIFF stream.
/// Stage ticks are aggregate worker time; wall ticks measure elapsed pipeline time.
/// </summary>
internal sealed class ExperimentalTiffProfile
{
	internal readonly int PipelineWorkers;
	internal readonly int PipelineQueueDepth;
	internal long PipelineStartedTimestamp;
	internal long PipelineCompletedTimestamp;
	internal long SnapshotTicks;
	internal long InputQueueWaitTicks;
	internal long PrepareTicks;
	internal long ByteCopyTicks;
	internal long DeflateTicks;
	internal long EncodedQueueWaitTicks;
	internal long RawCommitTicks;
	internal long TilesSubmitted;
	internal long TilesPrepared;
	internal long TilesCommitted;
	internal long UncompressedBytes;
	internal long CompressedBytes;
	internal long FloatBuffersAllocated;
	internal long ByteBuffersAllocated;
	internal long CompressedBuffersAllocated;
	internal int MaximumInputQueueDepth;
	internal int MaximumEncodedQueueDepth;
	internal int OwnedTiles;
	internal int MaximumOwnedTiles;

	internal ExperimentalTiffProfile()
	{
		PipelineWorkers = ExperimentalTiffSettings.PipelineWorkers;
		PipelineQueueDepth = ExperimentalTiffSettings.PipelineQueueDepth;
	}

	internal static double Seconds(long ticks)
	{
		return (double)ticks / Stopwatch.Frequency;
	}

	internal static void ObserveMaximum(ref int target, int value)
	{
		int observed = Volatile.Read(ref target);
		while (value > observed)
		{
			int prior = Interlocked.CompareExchange(ref target, value, observed);
			if (prior == observed)
			{
				return;
			}
			observed = prior;
		}
	}
}

internal static class ExperimentalTiffProfileRegistry
{
	private static readonly ConcurrentDictionary<string, ExperimentalTiffProfile> Profiles =
		new ConcurrentDictionary<string, ExperimentalTiffProfile>(StringComparer.OrdinalIgnoreCase);

	internal static ExperimentalTiffProfile GetOrCreate(string filename)
	{
		return Profiles.GetOrAdd(Normalize(filename), _ => new ExperimentalTiffProfile());
	}

	internal static ExperimentalTiffProfile Take(string filename)
	{
		ExperimentalTiffProfile profile;
		return Profiles.TryRemove(Normalize(filename), out profile)
			? profile
			: new ExperimentalTiffProfile();
	}

	private static string Normalize(string filename)
	{
		try
		{
			return Path.GetFullPath(filename);
		}
		catch
		{
			return filename ?? string.Empty;
		}
	}
}

internal sealed class ExperimentalArrayPool<T>
{
	private readonly ConcurrentBag<T[]> _items = new ConcurrentBag<T[]>();
	private readonly int _maximumRetained;
	private readonly Action _allocated;

	internal ExperimentalArrayPool(int maximumRetained, Action allocated)
	{
		_maximumRetained = Math.Max(1, maximumRetained);
		_allocated = allocated;
	}

	internal T[] Rent(int minimumLength)
	{
		T[] item;
		while (_items.TryTake(out item))
		{
			if (item.Length >= minimumLength)
			{
				return item;
			}
		}
		_allocated();
		return new T[minimumLength];
	}

	internal void Return(T[] item)
	{
		if (item != null && _items.Count < _maximumRetained)
		{
			_items.Add(item);
		}
	}
}

internal sealed class ExperimentalRawTileEncoder : IDisposable
{
	private readonly MemoryStream _stream;
	private readonly Tiff _tiff;
	private readonly int _maximumEncodedBytes;
	private bool _disposed;

	internal ExperimentalRawTileEncoder(int tileWidth, int tileHeight, int uncompressedBytes)
	{
		// Deflate's incompressible-data overhead is far below 64 KiB for a
		// native 256 KiB tile. Renting one fixed upper-bound buffer avoids a
		// stream of progressively larger compressed-array allocations as tile
		// entropy varies across a watershed.
		_maximumEncodedBytes = checked(uncompressedBytes + 64 * 1024);
		_stream = new MemoryStream(_maximumEncodedBytes);
		_tiff = Tiff.ClientOpen("ras-commander-parallel-tile-encoder", "w", _stream, new TiffStream());
		if (_tiff == null)
		{
			throw new InvalidOperationException("Could not create the in-memory TIFF tile encoder.");
		}
		_tiff.SetField(TiffTag.IMAGEWIDTH, tileWidth);
		_tiff.SetField(TiffTag.IMAGELENGTH, tileHeight);
		_tiff.SetField(TiffTag.TILEWIDTH, tileWidth);
		_tiff.SetField(TiffTag.TILELENGTH, tileHeight);
		_tiff.SetField(TiffTag.SAMPLESPERPIXEL, 1);
		_tiff.SetField(TiffTag.BITSPERSAMPLE, 32);
		_tiff.SetField(TiffTag.PLANARCONFIG, PlanarConfig.CONTIG);
		_tiff.SetField(TiffTag.ORIENTATION, Orientation.TOPLEFT);
		_tiff.SetField(TiffTag.SAMPLEFORMAT, SampleFormat.IEEEFP);
		_tiff.SetField(TiffTag.PHOTOMETRIC, Photometric.MINISBLACK);
		_tiff.SetField(TiffTag.COMPRESSION, Compression.ADOBE_DEFLATE);
		_tiff.SetField(TiffTag.ZIPQUALITY, 1);
		_tiff.SetField(TiffTag.FILLORDER, FillOrder.MSB2LSB);
	}

	internal ExperimentalEncodedBuffer Encode(
		byte[] input,
		int count,
		ExperimentalArrayPool<byte> outputPool)
	{
		int written = _tiff.WriteEncodedTile(0, input, 0, count);
		if (written != count)
		{
			throw new IOException("The in-memory TIFF encoder did not accept the complete tile.");
		}
		long rawSize = _tiff.RawTileSize(0);
		if (rawSize < 1 || rawSize > int.MaxValue)
		{
			throw new IOException("The in-memory TIFF encoder returned an invalid raw tile size.");
		}
		int rawCount = checked((int)rawSize);
		if (rawCount > _maximumEncodedBytes)
		{
			throw new IOException("The encoded tile exceeded its bounded output buffer.");
		}
		byte[] output = outputPool.Rent(_maximumEncodedBytes);
		int read = _tiff.ReadRawTile(0, output, 0, rawCount);
		if (read != rawCount)
		{
			outputPool.Return(output);
			throw new IOException("The in-memory TIFF encoder could not read its raw tile payload.");
		}
		return new ExperimentalEncodedBuffer(output, rawCount);
	}

	public void Dispose()
	{
		if (_disposed)
		{
			return;
		}
		_disposed = true;
		_tiff.Dispose();
	}
}

internal sealed class ExperimentalEncodedBuffer
{
	internal readonly byte[] Buffer;
	internal readonly int Count;

	internal ExperimentalEncodedBuffer(byte[] buffer, int count)
	{
		Buffer = buffer;
		Count = count;
	}
}

internal sealed class ExperimentalFloatTilePipeline : IDisposable
{
	private sealed class TileWorkItem
	{
		internal readonly int TileNumber;
		internal readonly float[] Values;
		internal readonly int ValueCount;

		internal TileWorkItem(int tileNumber, float[] values, int valueCount)
		{
			TileNumber = tileNumber;
			Values = values;
			ValueCount = valueCount;
		}
	}

	private sealed class EncodedTileItem
	{
		internal readonly int TileNumber;
		internal readonly byte[] Buffer;
		internal readonly int Count;
		internal readonly Stats Statistics;

		internal EncodedTileItem(int tileNumber, byte[] buffer, int count, Stats statistics)
		{
			TileNumber = tileNumber;
			Buffer = buffer;
			Count = count;
			Statistics = statistics;
		}
	}

	private readonly BlockingCollection<TileWorkItem> _input;
	private readonly BlockingCollection<EncodedTileItem> _encoded;
	private readonly CancellationTokenSource _cancellation = new CancellationTokenSource();
	private readonly Task[] _workers;
	private readonly Task _commitTask;
	private readonly ExperimentalArrayPool<float> _floatPool;
	private readonly ExperimentalArrayPool<byte> _bytePool;
	private readonly ExperimentalArrayPool<byte> _compressedPool;
	private readonly Func<int, float[], Stats> _prepare;
	private readonly Action<int, byte[], int, Stats> _commit;
	private readonly ExperimentalTiffProfile _profile;
	private readonly int _tileWidth;
	private readonly int _tileHeight;
	private readonly object _completionLock = new object();
	private Exception _failure;
	private bool _completed;
	private bool _disposed;

	internal ExperimentalFloatTilePipeline(
		string targetFilename,
		int tileWidth,
		int tileHeight,
		Func<int, float[], Stats> prepare,
		Action<int, byte[], int, Stats> commit)
	{
		_tileWidth = tileWidth;
		_tileHeight = tileHeight;
		_prepare = prepare ?? throw new ArgumentNullException(nameof(prepare));
		_commit = commit ?? throw new ArgumentNullException(nameof(commit));
		_profile = ExperimentalTiffProfileRegistry.GetOrCreate(targetFilename);
		_profile.PipelineStartedTimestamp = Stopwatch.GetTimestamp();

		int queueDepth = _profile.PipelineQueueDepth;
		int retained = queueDepth + _profile.PipelineWorkers + 2;
		_input = new BlockingCollection<TileWorkItem>(queueDepth);
		_encoded = new BlockingCollection<EncodedTileItem>(queueDepth);
		_floatPool = new ExperimentalArrayPool<float>(retained, () => Interlocked.Increment(ref _profile.FloatBuffersAllocated));
		_bytePool = new ExperimentalArrayPool<byte>(retained, () => Interlocked.Increment(ref _profile.ByteBuffersAllocated));
		_compressedPool = new ExperimentalArrayPool<byte>(retained, () => Interlocked.Increment(ref _profile.CompressedBuffersAllocated));

		_workers = new Task[_profile.PipelineWorkers];
		for (int index = 0; index < _workers.Length; index++)
		{
			_workers[index] = Task.Factory.StartNew(
				WorkerLoop,
				CancellationToken.None,
				TaskCreationOptions.LongRunning,
				TaskScheduler.Default
			);
		}
		_commitTask = Task.Factory.StartNew(
			CommitLoop,
			CancellationToken.None,
			TaskCreationOptions.LongRunning,
			TaskScheduler.Default
		);
	}

	internal void Enqueue(int tileNumber, float[] values)
	{
		if (values == null)
		{
			throw new ArgumentNullException(nameof(values));
		}
		ThrowIfUnavailable();
		long started = Stopwatch.GetTimestamp();
		float[] owned = _floatPool.Rent(values.Length);
		Array.Copy(values, 0, owned, 0, values.Length);
		Interlocked.Add(ref _profile.SnapshotTicks, Stopwatch.GetTimestamp() - started);
		Submit(new TileWorkItem(tileNumber, owned, values.Length));
	}

	internal void Enqueue(int tileNumber, float[,] values)
	{
		if (values == null)
		{
			throw new ArgumentNullException(nameof(values));
		}
		ThrowIfUnavailable();
		long started = Stopwatch.GetTimestamp();
		float[] owned = _floatPool.Rent(values.Length);
		Buffer.BlockCopy(values, 0, owned, 0, checked(values.Length * sizeof(float)));
		Interlocked.Add(ref _profile.SnapshotTicks, Stopwatch.GetTimestamp() - started);
		Submit(new TileWorkItem(tileNumber, owned, values.Length));
	}

	internal void Complete()
	{
		lock (_completionLock)
		{
			if (_completed)
			{
				ThrowIfFailed();
				return;
			}
			_input.CompleteAdding();
			try
			{
				Task.WaitAll(_workers);
			}
			catch (AggregateException ex)
			{
				RecordFailure(ex.Flatten().InnerExceptions[0]);
			}
			finally
			{
				_encoded.CompleteAdding();
			}
			try
			{
				_commitTask.Wait();
			}
			catch (AggregateException ex)
			{
				RecordFailure(ex.Flatten().InnerExceptions[0]);
			}
			_profile.PipelineCompletedTimestamp = Stopwatch.GetTimestamp();
			_completed = true;
			ThrowIfFailed();
		}
	}

	public void Dispose()
	{
		if (_disposed)
		{
			return;
		}
		try
		{
			Complete();
		}
		finally
		{
			_disposed = true;
			_cancellation.Dispose();
			_input.Dispose();
			_encoded.Dispose();
		}
	}

	private void Submit(TileWorkItem item)
	{
		int owned = Interlocked.Increment(ref _profile.OwnedTiles);
		ExperimentalTiffProfile.ObserveMaximum(ref _profile.MaximumOwnedTiles, owned);
		long started = Stopwatch.GetTimestamp();
		try
		{
			_input.Add(item, _cancellation.Token);
		}
		catch
		{
			Interlocked.Decrement(ref _profile.OwnedTiles);
			_floatPool.Return(item.Values);
			throw;
		}
		finally
		{
			Interlocked.Add(ref _profile.InputQueueWaitTicks, Stopwatch.GetTimestamp() - started);
		}
		Interlocked.Increment(ref _profile.TilesSubmitted);
		ExperimentalTiffProfile.ObserveMaximum(ref _profile.MaximumInputQueueDepth, _input.Count);
	}

	private void WorkerLoop()
	{
		try
		{
			using (ExperimentalRawTileEncoder encoder = new ExperimentalRawTileEncoder(
				_tileWidth,
				_tileHeight,
				checked(_tileWidth * _tileHeight * sizeof(float))))
			{
				foreach (TileWorkItem item in _input.GetConsumingEnumerable(_cancellation.Token))
				{
					ProcessTile(item, encoder);
				}
			}
		}
		catch (OperationCanceledException) when (_cancellation.IsCancellationRequested)
		{
			if (_failure == null)
			{
				return;
			}
		}
		catch (Exception ex)
		{
			RecordFailure(ex);
			_cancellation.Cancel();
			throw;
		}
	}

	private void ProcessTile(TileWorkItem item, ExperimentalRawTileEncoder encoder)
	{
		byte[] uncompressed = null;
		ExperimentalEncodedBuffer encoded = null;
		bool valuesReturned = false;
		try
		{
			long started = Stopwatch.GetTimestamp();
			Stats statistics = _prepare(item.TileNumber, item.Values);
			Interlocked.Add(ref _profile.PrepareTicks, Stopwatch.GetTimestamp() - started);

			int byteCount = checked(item.ValueCount * sizeof(float));
			uncompressed = _bytePool.Rent(byteCount);
			started = Stopwatch.GetTimestamp();
			Buffer.BlockCopy(item.Values, 0, uncompressed, 0, byteCount);
			Interlocked.Add(ref _profile.ByteCopyTicks, Stopwatch.GetTimestamp() - started);
			_floatPool.Return(item.Values);
			valuesReturned = true;

			started = Stopwatch.GetTimestamp();
			encoded = encoder.Encode(uncompressed, byteCount, _compressedPool);
			Interlocked.Add(ref _profile.DeflateTicks, Stopwatch.GetTimestamp() - started);
			_bytePool.Return(uncompressed);
			uncompressed = null;

			Interlocked.Increment(ref _profile.TilesPrepared);
			Interlocked.Add(ref _profile.UncompressedBytes, byteCount);
			Interlocked.Add(ref _profile.CompressedBytes, encoded.Count);
			EncodedTileItem result = new EncodedTileItem(
				item.TileNumber,
				encoded.Buffer,
				encoded.Count,
				statistics);
			started = Stopwatch.GetTimestamp();
			_encoded.Add(result, _cancellation.Token);
			Interlocked.Add(ref _profile.EncodedQueueWaitTicks, Stopwatch.GetTimestamp() - started);
			ExperimentalTiffProfile.ObserveMaximum(ref _profile.MaximumEncodedQueueDepth, _encoded.Count);
			encoded = null;
		}
		finally
		{
			if (!valuesReturned)
			{
				_floatPool.Return(item.Values);
			}
			_bytePool.Return(uncompressed);
			if (encoded != null)
			{
				_compressedPool.Return(encoded.Buffer);
			}
		}
	}

	private void CommitLoop()
	{
		try
		{
			foreach (EncodedTileItem item in _encoded.GetConsumingEnumerable(_cancellation.Token))
			{
				try
				{
					long started = Stopwatch.GetTimestamp();
					_commit(item.TileNumber, item.Buffer, item.Count, item.Statistics);
					Interlocked.Add(ref _profile.RawCommitTicks, Stopwatch.GetTimestamp() - started);
					Interlocked.Increment(ref _profile.TilesCommitted);
					Interlocked.Decrement(ref _profile.OwnedTiles);
				}
				finally
				{
					_compressedPool.Return(item.Buffer);
				}
			}
		}
		catch (OperationCanceledException) when (_cancellation.IsCancellationRequested)
		{
			if (_failure == null)
			{
				return;
			}
		}
		catch (Exception ex)
		{
			RecordFailure(ex);
			_cancellation.Cancel();
			throw;
		}
	}

	private void ThrowIfUnavailable()
	{
		if (_disposed || _completed || _input.IsAddingCompleted)
		{
			throw new ObjectDisposedException(nameof(ExperimentalFloatTilePipeline));
		}
		ThrowIfFailed();
	}

	private void ThrowIfFailed()
	{
		if (_failure != null)
		{
			throw new InvalidOperationException("The experimental parallel TIFF pipeline failed.", _failure);
		}
	}

	private void RecordFailure(Exception failure)
	{
		if (failure == null)
		{
			return;
		}
		Interlocked.CompareExchange(ref _failure, failure, null);
	}
}

/// <summary>
/// Creates a LibTiff client stream only for opt-in writes. Reads and normal
/// unpatched behavior continue through Tiff.Open.
/// </summary>
internal static class ExperimentalTiffStreamFactory
{
	internal static Tiff Open(string filename, string mode)
	{
		FileStream file = null;
		InstrumentedBatchingStream stream = null;
		try
		{
			file = new FileStream(
				filename,
				FileMode.Create,
				FileAccess.ReadWrite,
				FileShare.Read,
				4096,
				FileOptions.None
			);
			stream = new InstrumentedBatchingStream(
				file,
				ExperimentalTiffSettings.BatchBytes,
				filename
			);
			Tiff tiff = Tiff.ClientOpen(filename, mode, stream, new TiffStream());
			if (tiff == null)
			{
				stream.Dispose();
				return null;
			}
			return tiff;
		}
		catch
		{
			if (stream != null)
			{
				stream.Dispose();
			}
			else if (file != null)
			{
				file.Dispose();
			}
			throw;
		}
	}
}

/// <summary>
/// A seek-aware write-behind stream for LibTiff.NET. Contiguous small writes
/// are coalesced until the configured threshold. A seek within the pending
/// range is serviced in-memory; an incompatible seek flushes first.
/// </summary>
internal sealed class InstrumentedBatchingStream : Stream
{
	private readonly FileStream _inner;
	private readonly byte[] _buffer;
	private readonly string _targetFilename;
	private long _position;
	private long _bufferStart = -1;
	private int _bufferLength;
	private bool _disposed;
	private long _logicalWriteCalls;
	private long _logicalWriteBytes;
	private long _underlyingWriteCalls;
	private long _underlyingWriteBytes;
	private int _minimumUnderlyingWrite = int.MaxValue;
	private int _maximumUnderlyingWrite;
	private long _flushCalls;
	private long _seekCalls;

	internal InstrumentedBatchingStream(FileStream inner, int batchBytes, string targetFilename)
	{
		_inner = inner ?? throw new ArgumentNullException(nameof(inner));
		_buffer = new byte[batchBytes];
		_targetFilename = targetFilename;
		_position = inner.Position;
	}

	public override bool CanRead => !_disposed && _inner.CanRead;
	public override bool CanSeek => !_disposed && _inner.CanSeek;
	public override bool CanWrite => !_disposed && _inner.CanWrite;

	public override long Length
	{
		get
		{
			EnsureOpen();
			long pendingEnd = _bufferStart < 0 ? 0 : _bufferStart + _bufferLength;
			return Math.Max(_inner.Length, pendingEnd);
		}
	}

	public override long Position
	{
		get => _position;
		set => Seek(value, SeekOrigin.Begin);
	}

	public override void Flush()
	{
		EnsureOpen();
		FlushPending();
		_inner.Flush();
		_flushCalls++;
	}

	public override int Read(byte[] buffer, int offset, int count)
	{
		EnsureOpen();
		FlushPending();
		_inner.Position = _position;
		int read = _inner.Read(buffer, offset, count);
		_position += read;
		return read;
	}

	public override long Seek(long offset, SeekOrigin origin)
	{
		EnsureOpen();
		_seekCalls++;
		long target;
		switch (origin)
		{
		case SeekOrigin.Begin:
			target = offset;
			break;
		case SeekOrigin.Current:
			target = checked(_position + offset);
			break;
		case SeekOrigin.End:
			target = checked(Length + offset);
			break;
		default:
			throw new ArgumentOutOfRangeException(nameof(origin));
		}
		if (target < 0)
		{
			throw new IOException("Cannot seek before the beginning of the TIFF stream.");
		}

		if (_bufferStart >= 0 && target >= _bufferStart &&
			target <= _bufferStart + _bufferLength)
		{
			_position = target;
			return _position;
		}

		FlushPending();
		_position = _inner.Seek(target, SeekOrigin.Begin);
		return _position;
	}

	public override void SetLength(long value)
	{
		EnsureOpen();
		FlushPending();
		_inner.SetLength(value);
		if (_position > value)
		{
			_position = value;
		}
	}

	public override void Write(byte[] buffer, int offset, int count)
	{
		EnsureOpen();
		if (buffer == null)
		{
			throw new ArgumentNullException(nameof(buffer));
		}
		if (offset < 0 || count < 0 || offset + count > buffer.Length)
		{
			throw new ArgumentOutOfRangeException();
		}
		_logicalWriteCalls++;
		_logicalWriteBytes += count;

		if (count >= _buffer.Length)
		{
			FlushPending();
			WriteUnderlying(_position, buffer, offset, count);
			_position += count;
			return;
		}

		if (_bufferStart < 0)
		{
			_bufferStart = _position;
			_bufferLength = 0;
		}

		long relative = _position - _bufferStart;
		if (relative < 0 || relative + count > _buffer.Length)
		{
			FlushPending();
			_bufferStart = _position;
			relative = 0;
		}

		Buffer.BlockCopy(buffer, offset, _buffer, checked((int)relative), count);
		_bufferLength = Math.Max(_bufferLength, checked((int)relative) + count);
		_position += count;
		if (_bufferLength == _buffer.Length)
		{
			FlushPending();
		}
	}

	protected override void Dispose(bool disposing)
	{
		if (_disposed)
		{
			base.Dispose(disposing);
			return;
		}
		if (disposing)
		{
			try
			{
				FlushPending();
				_inner.Flush();
			}
			finally
			{
				_inner.Dispose();
				_disposed = true;
				if (ExperimentalTiffSettings.WriteProfile)
				{
					WriteProfile();
				}
			}
		}
		base.Dispose(disposing);
	}

	private void FlushPending()
	{
		if (_bufferStart < 0 || _bufferLength == 0)
		{
			_bufferStart = -1;
			_bufferLength = 0;
			return;
		}
		WriteUnderlying(_bufferStart, _buffer, 0, _bufferLength);
		_bufferStart = -1;
		_bufferLength = 0;
	}

	private void WriteUnderlying(long position, byte[] buffer, int offset, int count)
	{
		_inner.Position = position;
		_inner.Write(buffer, offset, count);
		_underlyingWriteCalls++;
		_underlyingWriteBytes += count;
		_minimumUnderlyingWrite = Math.Min(_minimumUnderlyingWrite, count);
		_maximumUnderlyingWrite = Math.Max(_maximumUnderlyingWrite, count);
	}

	private void WriteProfile()
	{
		double mean = _underlyingWriteCalls == 0
			? 0.0
			: (double)_underlyingWriteBytes / _underlyingWriteCalls;
		int minimum = _underlyingWriteCalls == 0 ? 0 : _minimumUnderlyingWrite;
		ExperimentalTiffProfile profile = ExperimentalTiffProfileRegistry.Take(_targetFilename);
		long wallTicks = profile.PipelineCompletedTimestamp > profile.PipelineStartedTimestamp
			? profile.PipelineCompletedTimestamp - profile.PipelineStartedTimestamp
			: 0;
		StringBuilder json = new StringBuilder();
		json.AppendLine("{");
		AppendJson(json, "schema", "ras-commander.experimental-tiff-io/2", true);
		AppendJson(json, "batch_bytes", _buffer.Length, true);
		AppendJson(json, "statistics_mode", ExperimentalTiffSettings.StatisticsMode, true);
		AppendJson(json, "reuse_tile_buffer", ExperimentalTiffSettings.ReuseTileBuffer, true);
		AppendJson(json, "logical_write_calls", _logicalWriteCalls, true);
		AppendJson(json, "logical_write_bytes", _logicalWriteBytes, true);
		AppendJson(json, "underlying_write_calls", _underlyingWriteCalls, true);
		AppendJson(json, "underlying_write_bytes", _underlyingWriteBytes, true);
		AppendJson(json, "mean_underlying_write_bytes", mean, true);
		AppendJson(json, "minimum_underlying_write_bytes", minimum, true);
		AppendJson(json, "maximum_underlying_write_bytes", _maximumUnderlyingWrite, true);
		AppendJson(json, "flush_calls", _flushCalls, true);
		AppendJson(json, "seek_calls", _seekCalls, true);
		AppendJson(json, "pipeline_enabled", profile.PipelineWorkers > 0, true);
		AppendJson(json, "pipeline_workers", profile.PipelineWorkers, true);
		AppendJson(json, "pipeline_queue_depth", profile.PipelineQueueDepth, true);
		AppendJson(json, "pipeline_wall_seconds", ExperimentalTiffProfile.Seconds(wallTicks), true);
		AppendJson(json, "snapshot_seconds", ExperimentalTiffProfile.Seconds(Interlocked.Read(ref profile.SnapshotTicks)), true);
		AppendJson(json, "input_queue_wait_seconds", ExperimentalTiffProfile.Seconds(Interlocked.Read(ref profile.InputQueueWaitTicks)), true);
		AppendJson(json, "prepare_seconds", ExperimentalTiffProfile.Seconds(Interlocked.Read(ref profile.PrepareTicks)), true);
		AppendJson(json, "byte_copy_seconds", ExperimentalTiffProfile.Seconds(Interlocked.Read(ref profile.ByteCopyTicks)), true);
		AppendJson(json, "deflate_seconds", ExperimentalTiffProfile.Seconds(Interlocked.Read(ref profile.DeflateTicks)), true);
		AppendJson(json, "encoded_queue_wait_seconds", ExperimentalTiffProfile.Seconds(Interlocked.Read(ref profile.EncodedQueueWaitTicks)), true);
		AppendJson(json, "raw_commit_seconds", ExperimentalTiffProfile.Seconds(Interlocked.Read(ref profile.RawCommitTicks)), true);
		AppendJson(json, "tiles_submitted", Interlocked.Read(ref profile.TilesSubmitted), true);
		AppendJson(json, "tiles_prepared", Interlocked.Read(ref profile.TilesPrepared), true);
		AppendJson(json, "tiles_committed", Interlocked.Read(ref profile.TilesCommitted), true);
		AppendJson(json, "uncompressed_tile_bytes", Interlocked.Read(ref profile.UncompressedBytes), true);
		AppendJson(json, "compressed_tile_bytes", Interlocked.Read(ref profile.CompressedBytes), true);
		AppendJson(json, "float_buffers_allocated", Interlocked.Read(ref profile.FloatBuffersAllocated), true);
		AppendJson(json, "byte_buffers_allocated", Interlocked.Read(ref profile.ByteBuffersAllocated), true);
		AppendJson(json, "compressed_buffers_allocated", Interlocked.Read(ref profile.CompressedBuffersAllocated), true);
		AppendJson(json, "maximum_input_queue_depth", Volatile.Read(ref profile.MaximumInputQueueDepth), true);
		AppendJson(json, "maximum_encoded_queue_depth", Volatile.Read(ref profile.MaximumEncodedQueueDepth), true);
		AppendJson(json, "maximum_owned_tiles", Volatile.Read(ref profile.MaximumOwnedTiles), false);
		json.AppendLine("}");
		File.WriteAllText(_targetFilename + ".rascommander-tiff-profile.json", json.ToString(), Encoding.UTF8);
	}

	private static void AppendJson(StringBuilder builder, string name, object value, bool comma)
	{
		builder.Append("  ").Append('"').Append(name).Append("\": ");
		if (value is string)
		{
			builder.Append('"').Append(((string)value).Replace("\\", "\\\\").Replace("\"", "\\\"")).Append('"');
		}
		else if (value is bool)
		{
			builder.Append(((bool)value) ? "true" : "false");
		}
		else if (value is double)
		{
			builder.Append(((double)value).ToString("F6", CultureInfo.InvariantCulture));
		}
		else
		{
			builder.Append(Convert.ToString(value, CultureInfo.InvariantCulture));
		}
		if (comma)
		{
			builder.Append(',');
		}
		builder.AppendLine();
	}

	private void EnsureOpen()
	{
		if (_disposed)
		{
			throw new ObjectDisposedException(nameof(InstrumentedBatchingStream));
		}
	}
}
