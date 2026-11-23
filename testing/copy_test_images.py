import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SOURCE_DIR = PROJECT_ROOT / "riistakamera_kuvat"
TARGET_DIR = PROJECT_ROOT / "20_test"
NAMES_FILE = Path(__file__).parent / "20_test_pic_names.txt"

TARGET_DIR.mkdir(exist_ok=True)

names = [line.strip() for line in NAMES_FILE.read_text().splitlines() if line.strip()]
copied = 0

for name in names:
    src = SOURCE_DIR / f"{name}.jpg"
    if src.exists():
        shutil.copy2(src, TARGET_DIR / src.name)
        print(f"Kopioitu: {src.name}")
        copied += 1
    else:
        print(f"Ei löydy: {src.name}")

print(f"\n{copied}/{len(names)} kuvaa kopioitu kansioon {TARGET_DIR.name}")
