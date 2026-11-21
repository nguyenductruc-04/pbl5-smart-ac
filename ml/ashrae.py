"""
Tai va loc ASHRAE Global Thermal Comfort Database II (v2.1.0) cho mo hinh tien nghi.

Nguon: kho chinh thuc cua Center for the Built Environment, co dinh theo commit de ket qua tai lap duoc.
Du lieu goc KHONG duoc commit vao repo (ml/data/ nam trong .gitignore); chi commit tham so da hoc.

Trich dan: Parkinson T., Tartarini F., Foldvary Licina V. et al. (2022). ASHRAE global database of
thermal comfort field measurements [Dataset]. Dryad. https://doi.org/10.6078/D1F671
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import pandas as pd

REPO = "CenterForTheBuiltEnvironment/ashrae-db-II"
COMMIT = "c527d6115ebadb4725a4e1406b2439a7a1ffd214"
FILES = ("v2.1.0/db_measurements_v2.1.0.csv.gz", "v2.1.0/db_metadata.csv")
DATA_DIR = Path(__file__).resolve().parent / "data"

# Vung khi hau giong Viet Nam: nhiet doi (Koppen A) va can nhiet doi gio mua (Cwa, nhu Ha Noi)
CLIMATES = (
    "tropical", "tropical rainforest", "tropical monsoon", "tropical savanna", "tropical wet savanna",
    "monsoon-influenced humid subtropical",
)
CLASS_INDEX = {"warmer": 0, "no change": 1, "cooler": 2}


def download(data_dir: Path = DATA_DIR) -> list[Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in FILES:
        dest = data_dir / Path(name).name
        if not dest.exists():
            url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{name}"
            print(f"Tai {url}")
            urllib.request.urlretrieve(url, dest)
        paths.append(dest)
    return paths


def load(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Phieu co du nhiet do khong khi, do am va mong muon nhiet, o vung khi hau da chon."""
    meas_path, meta_path = download(data_dir)
    meas = pd.read_csv(meas_path, low_memory=False)
    meta = pd.read_csv(meta_path)
    d = meas.merge(meta[["building_id", "country", "climate", "cooling_type", "quality_assurance"]],
                   on="building_id", how="left")
    d = d[d["thermal_preference"].isin(CLASS_INDEX) & d["ta"].notna() & d["rh"].notna()]
    d = d[d["climate"].isin(CLIMATES) & (d["quality_assurance"] == "pass")]
    # Bo gia tri vo ly (loi nhap lieu): ngoai khoang nhiet do / do am trong nha binh thuong
    d = d[d["ta"].between(15, 40) & d["rh"].between(10, 100)]
    out = pd.DataFrame({
        "ta": d["ta"].astype(float),
        "rh": d["rh"].astype(float),
        "cls": d["thermal_preference"].map(CLASS_INDEX).astype(int),
        "building_id": d["building_id"].astype(int),
        "cooling_type": d["cooling_type"],
        "country": d["country"],
    })
    return out.reset_index(drop=True)
