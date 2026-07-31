"""Run one AMPL script in an isolated working directory."""
import json
import os
import sys
import time
from importlib import metadata as importlib_metadata
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path


def run_ampl_script(run_path, working_directory, result_directory):
    run_path = Path(run_path).resolve()
    working_directory = Path(working_directory).resolve()
    result_directory = Path(result_directory).resolve()
    result_directory.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    stdout = StringIO()
    stderr = StringIO()
    result = {
        "run_script": run_path.name,
        "status": "failed",
        "statistics": {},
        "diagnostics": {
            "python_executable": sys.executable,
            "python_version": sys.version,
            "ampl_path": os.environ.get("AMPL_PATH", ""),
            "path": os.environ.get("PATH", ""),
        },
    }

    try:
        result["diagnostics"]["amplpy_version"] = importlib_metadata.version("amplpy")
    except importlib_metadata.PackageNotFoundError:
        result["diagnostics"]["amplpy_version"] = None

    try:
        from amplpy import AMPL, add_to_path, modules
        import amplpy
        result["diagnostics"]["amplpy_path"] = str(Path(amplpy.__file__).resolve())
    except ImportError as error:
        result["error"] = "The amplpy Python library is not available to the configured Python interpreter."
        result["diagnostics"]["import_error"] = repr(error)
    else:
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                ampl_path = os.environ.get("AMPL_PATH")
                if ampl_path:
                    add_to_path(ampl_path)
                modules.load()
                result["diagnostics"]["modules_loaded"] = True
                os.chdir(working_directory)
                ampl = AMPL()
                try:
                    # Include executes the .run script with relative paths resolved here.
                    ampl.eval(f'include "{run_path.name}";')
                    result["status"] = "completed"
                    result["statistics"] = {
                        "working_directory": str(working_directory),
                        "model_file_count": len(list(working_directory.glob("*.mod"))),
                        "data_file_count": len(list(working_directory.glob("*.dat"))),
                    }
                finally:
                    ampl.close()
        except Exception as error:
            result["error"] = str(error)
            result["diagnostics"]["runtime_error"] = repr(error)

    result["duration_seconds"] = round(time.monotonic() - started, 3)
    result["stdout"] = stdout.getvalue()
    result["stderr"] = stderr.getvalue()
    (result_directory / "stdout.txt").write_text(result["stdout"], encoding="utf-8")
    (result_directory / "stderr.txt").write_text(result["stderr"], encoding="utf-8")
    (result_directory / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: analysis_runner.py RUN_FILE WORKING_DIRECTORY RESULT_DIRECTORY")
    print(json.dumps(run_ampl_script(sys.argv[1], sys.argv[2], sys.argv[3])))