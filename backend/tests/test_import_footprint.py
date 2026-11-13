import subprocess
import sys
from pathlib import Path

HEAVY = ("openai", "google.auth", "PIL", "pypdfium2", "fastapi")


def test_celery_workers_do_not_import_heavy_sdks() -> None:
    # Every worker imports every task module, so a module-level SDK import costs
    # RAM in each pool process of every container. Fresh interpreter: the test
    # session itself has already imported everything.
    code = (
        "import sys\n"
        "from app.celery_app import celery_app\n"
        "celery_app.loader.import_default_modules()\n"
        f"print(sorted(m for m in {HEAVY!r} if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]"
