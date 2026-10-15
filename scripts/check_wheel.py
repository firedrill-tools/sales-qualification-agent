"""Exercise bundled case selection and reset outside the source checkout."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

wheel, = Path("dist").glob("*.whl")
with ZipFile(wheel) as archive:
    assert "sales_qualification/sample_data/manifest.json" in archive.namelist()
    assert len([name for name in archive.namelist() if name.startswith("sales_qualification/sample_data/") and name.endswith(".json")]) == 9
    with TemporaryDirectory(prefix="sales-qualification-wheel-") as directory:
        archive.extractall(directory)
        script = '''
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from sales_qualification import cli
assert Path(cli.__file__).is_relative_to(Path(sys.argv[1]))
assert cli.main(["--list-cases"]) == 0
raise SystemExit(cli.main(["--init-case", "busy", "--workspace", str(Path(sys.argv[1]) / "state.json")]))
'''
        checked = subprocess.run([sys.executable, "-c", script, directory], cwd=directory,
                                 text=True, capture_output=True, check=True)
        listed, initialized = [json.loads(line) for line in checked.stdout.splitlines()]
        assert listed["case_count"] == 8 and listed["version"] == "1.0.0"
        assert initialized["dataset"]["case_id"] == "busy"
print("Packaged CLI lists all eight inputs and initializes a verified workspace outside the checkout; no model called.")
