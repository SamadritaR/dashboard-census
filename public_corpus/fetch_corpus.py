"""Download the public corpus: Tableau workbooks published on GitHub by 19 authors.

The workbooks belong to their authors, so they are not copied into this repo.
This script pulls each repo at the exact commit used for the results in the README,
extracts every .twb (unzipping .twbx), drops duplicates, and fetches the Global
Superstore data used to price the conflicts.

python public_corpus/fetch_corpus.py
"""
import hashlib
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
REPOS = {
    "Kartik-Arora18/Tableau-dashboard": "7fa963b86c6bb924b574a85d3fabb360bc1f9846",
    "MariKoh/tableau-dashboards": "3817b2135a08d09d3d8e9ba411c1503249d78f4d",
    "PrigasG/twbparser": "c0a0b7ccdc68ff4a290f819ccb385a8d90e7ea28",
    "SimonJahan/Tableau-Workbook-Extractor": "65ec86c50648db7dc805f0e06dd87e3df5277db1",
    "andey0Saikiran/tableau-lineage": "35c20b60812ce360af1aea08a8fa6f2df548b097",
    "asharma07/Tableau": "1884b717ff406b86b2ed6a827cfa3934b9122e53",
    "ayushshinde19/Tableau-dashboard-": "89d56fb86183d2ef8e395f4f82ea19d5c5468ece",
    "babaraokalyankar/Tableau-Dashboards": "43b7470e7e215dfd8b288663c8a9dbd50a938f23",
    "ionutsd/twbx_to_pbip": "69b89785bfbaffca0e517724df80cf59f4a478b3",
    "jayutekar/Tableau-Workbook": "f5bb985735c5034e29498b9a146c001e8e9483b1",
    "konpuku/tableau-workbook-documenter": "122472ccd37225cf45897eface877299015fb38a",
    "mr-milannn/Sales-Dashboard-using-Tableau": "5833cda2d28f822e9829aa809df8c6bfb63e53eb",
    "sandeep-coder/TDK_Tasks_Tableau_Dashboards": "a7e2cc0ec4e29d1991687ea0c39bedcc7fc54063",
    "sandro-mollica/TableauDoc": "ab67af3e145c41395c7a85c6b6e86bca32788bf8",
    "saurabhtayal/Tableau-Workbooks": "67db80637e767afe887b10ab3f9a8db3a5856634",
    "smd-saif/Tableau-Sales-Dashboard.twbx": "67d72514f2db7ecb9aeede6bd3f2be65705dbc54",
    "tableau/document-api-python": "447357fc1ad21945b31c0ed20d69593c13cc7921",
    "utkarsh-yadav1231/Tableau-Projects": "59747bf82f83806a6c4222c19bc068f091087a86",
    "vizyourdata/portfolio": "2122797a3d7f1bb1c30f97d430e4eecc45efbcc5",
}
DATA = ("ayushshinde19/Tableau-dashboard-", "global_superstore_2016.xlsx")


def checkout(repo: str, sha: str, dest: Path) -> None:
    run = lambda *a: subprocess.run(a, cwd=dest, check=True, capture_output=True)
    dest.mkdir(parents=True)
    run("git", "init", "-q")
    run("git", "fetch", "-q", "--depth", "1", f"https://github.com/{repo}.git", sha)
    run("git", "checkout", "-q", "FETCH_HEAD")


def main() -> None:
    out = HERE / "workbooks"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    seen, n = set(), 0
    with tempfile.TemporaryDirectory() as tmp:
        for repo, sha in REPOS.items():
            src = Path(tmp) / repo.replace("/", "__")
            checkout(repo, sha, src)
            for p in sorted(q for q in src.rglob("*") if q.is_file() and q.suffix.lower() in (".twb", ".twbx")):
                try:
                    if p.suffix.lower() == ".twbx":
                        z = zipfile.ZipFile(p)
                        data = z.read(next(i for i in z.namelist() if i.lower().endswith(".twb")))
                    else:
                        data = p.read_bytes()
                except Exception:
                    continue
                h = hashlib.md5(data).hexdigest()
                if h in seen:
                    continue
                seen.add(h)
                (out / f"{src.name}__{p.stem[:60]}.twb".replace(" ", "_")).write_bytes(data)
                n += 1
            if repo == DATA[0]:
                shutil.copy(src / DATA[1], HERE / DATA[1])
    print(f"{n} unique workbooks in {out}")


if __name__ == "__main__":
    main()
