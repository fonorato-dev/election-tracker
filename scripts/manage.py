"""Edit the encrypted race list or change the password.

  python scripts/manage.py export  PASSWORD            > source.json   # decrypt to edit
  python scripts/manage.py import  PASSWORD source.json                # re-encrypt after editing
  python scripts/manage.py rotate  OLD_PASSWORD NEW_PASSWORD           # change password

After 'rotate', also update the TRACKER_PASSWORD secret in GitHub (Settings > Secrets and variables > Actions).
Never commit source.json: it is the unencrypted watch list.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from crypto_util import decrypt, encrypt  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "data" / "source.enc"


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "export":
        print(json.dumps(decrypt(json.loads(SRC.read_text()), sys.argv[2]), indent=1))
    elif cmd == "import":
        SRC.write_text(json.dumps(encrypt(json.loads(Path(sys.argv[3]).read_text()), sys.argv[2])))
        print("data/source.enc updated")
    elif cmd == "rotate":
        SRC.write_text(json.dumps(encrypt(decrypt(json.loads(SRC.read_text()), sys.argv[2]), sys.argv[3])))
        print("data/source.enc re-encrypted. Update the TRACKER_PASSWORD secret, then run the workflow.")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
