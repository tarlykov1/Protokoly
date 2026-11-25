"""Build the same installable archive locally and in CI."""

import hashlib
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent


def build(destination):
    files = {}
    for name in [
        "README.md",
        "install.sh",
        "rollback.sh",
        "update-portal.sh",
        "portal.example.php",
        "protocol-groups.php",
        "controller-v8.service",
    ]:
        files[name] = (ROOT / name).read_bytes()
    for directory in ["portal", "server", "tests"]:
        for path in sorted((ROOT / directory).iterdir()):
            if path.is_file():
                files[str(path.relative_to(ROOT))] = path.read_bytes()
    for name in ["router_v3_18.py", "protocol_adapter.py", "memo_adapter.py"]:
        files["server/shared/" + name] = (ROOT.parent / name).read_bytes()
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())
    ).encode()
    with ZipFile(destination, "w") as archive:
        for name, data in sorted(files.items()):
            entry = ZipInfo("controller-v8/" + name)
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            archive.writestr(entry, data)


if __name__ == "__main__":
    build(sys.argv[1])
