"""Download source mental-health data into ./data.

Replace stubs with real fetchers (DSM/ICD condition catalogs, treatment
guidelines, medication databases). Keep each source in its own function.
"""
from pathlib import Path
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

def download_all() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    # TODO: download_conditions(); download_treatments(); download_medications()
    print(f"[download] wrote sources into {DATA_DIR}")

if __name__ == "__main__":
    download_all()
