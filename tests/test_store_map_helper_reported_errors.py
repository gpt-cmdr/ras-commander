"""Exercise the packaged .NET helper's native progress/error boundary."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def fake_mapper_runtime(tmp_path_factory):
    if os.name != "nt":
        pytest.skip("Packaged .NET Framework helper requires Windows")
    compiler = (
        Path(os.environ["WINDIR"])
        / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    )
    if not compiler.is_file():
        pytest.skip(".NET Framework C# compiler is unavailable")
    runtime = tmp_path_factory.mktemp("reported_native_errors")
    source = runtime / "MapperStub.cs"
    # This fixture tests exception propagation, not hydraulic or raster behavior.
    source.write_text(
        """
namespace Utility.Progress {
    public enum MessageType { Status, Warning, FatalError }
    public delegate void MessageHandler(string message, MessageType kind);
    public class ProgressReporter {
        public event MessageHandler MessageReported;
        public void Report(string message, MessageType kind) {
            if (MessageReported != null) MessageReported(message, kind);
        }
    }
}
namespace RasMapperLib {
    public static class SharedData {
        public static void SetHorizontalRenderingMode() { }
    }
}
namespace RasMapperLib.Scripting {
    public class StoreAllMapsCommand {
        string mode;
        public StoreAllMapsCommand(string rasmap, string result) { mode = result; }
        public void Execute(Utility.Progress.ProgressReporter reporter = null) {
            if (reporter == null) return;
            var kind = (Utility.Progress.MessageType)System.Enum.Parse(
                typeof(Utility.Progress.MessageType), mode);
            reporter.Report("synthetic native diagnostic", kind);
            // Native commands can report errors without throwing an exception.
        }
    }
}
""",
        encoding="utf-8",
    )
    subprocess.run(
        [str(compiler), "/nologo", "/target:library",
         f"/out:{runtime / 'RasMapperLib.dll'}", str(source)],
        check=True, capture_output=True, text=True,
    )
    (runtime / "test.rasmap").write_text("<RASMapper />", encoding="utf-8")
    return runtime


@pytest.mark.parametrize("kind", ["FatalError", "Warning", "Status"])
def test_packaged_helper_propagates_reported_native_errors(fake_mapper_runtime, kind):
    runtime = fake_mapper_runtime
    helper = Path(__file__).resolve().parents[1] / "ras_commander/native/RasStoreMapHelper.exe"
    result = subprocess.run(
        [str(helper), str(runtime), "horizontal", "StoreAllMaps",
         str(runtime / "test.rasmap"), kind],
        capture_output=True, text=True, timeout=30,
    )
    if kind == "FatalError":
        assert result.returncode != 0
        assert "NATIVE_FatalError: synthetic native diagnostic" in result.stderr
        assert "reported 1 error(s)" in result.stderr
        assert "completed successfully" not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert f"NATIVE_{kind}: synthetic native diagnostic" in result.stdout
        assert "completed successfully" in result.stdout
