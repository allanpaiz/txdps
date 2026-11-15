from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = [ROOT / name for name in ["README.md", "requirements.txt", ".gitignore", "data/README.md"]]
    for directory, pattern in [("pipeline", "*.py"), ("pipeline/sql", "*.sql"), (".github/workflows", "*.yml")]:
        files.extend((ROOT / directory).glob(pattern))
    files.extend(p for p in (ROOT / "docs").rglob("*") if p.is_file())
    required = ["docs/index.html", "docs/report.pdf", "docs/data/dashboard.json", "docs/data/counties.geojson",
                "docs/data/interstates.geojson", "docs/assets/overview.png", "docs/assets/frequency.png"]
    for name in required:
        if not (ROOT / name).is_file() or not (ROOT / name).stat().st_size:
            raise FileNotFoundError(name)
    target = ROOT / "release" / "txdps-public.zip"
    target.parent.mkdir(exist_ok=True)
    with ZipFile(target, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(ROOT))
    print(f"{target} ({target.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
