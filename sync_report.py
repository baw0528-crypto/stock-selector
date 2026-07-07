"""output/ のレポートスナップショットを docs/reports/ に暗号化して同期する。

screen.py を実行した後にこのスクリプトを叩くと、最新N件の report_*.json を
パスフレーズで暗号化(PBKDF2 + AES-256-GCM)して docs/reports/ にコピーし、
一覧表示用のマニフェスト(これも暗号化)を生成する。

docs/ はモバイル閲覧用PWA本体であると同時に、GitHub Pagesの公開ディレクトリ
(Settings > Pages > Source > /docs)としてそのまま使う想定。

リポジトリ(GitHub Pages配信元)を private にしても公開されるPagesのURL自体は
誰でも開けてしまうため、レポート本文はここで暗号化した状態でしか置かない。
復号はブラウザ側(js/crypto.js)で同じパスフレーズを使って行う。

使い方:
    # .env に MOBILE_DASHBOARD_PASSWORD を設定してから
    python sync_report.py
    python sync_report.py --keep 30
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

load_dotenv()

PBKDF2_ITERATIONS = 210_000
SALT_LEN = 16
NONCE_LEN = 12

OUTPUT_DIR = Path("output")
DASHBOARD_DIR = Path("docs")
REPORTS_DIR = DASHBOARD_DIR / "reports"

REPORT_RE = re.compile(r"^report_(\d{8}_\d{4})\.json$")


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
        backend=default_backend(),
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_json(obj: dict, passphrase: str) -> dict:
    """salt/nonce/ciphertextをすべてbase64にしたJSONラッパーを返す(ブラウザ側と共通形式)。"""
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = _derive_key(passphrase, salt)
    plaintext = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return {
        "v": 1,
        "kdf": "pbkdf2-sha256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def _top_preview(candidates: list[dict], n: int = 3) -> list[dict]:
    return [
        {"code": c["code"], "name": c["name"], "total_score": c["total_score"]}
        for c in candidates[:n]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", type=int, default=20, help="同期するレポートの最大件数(新しい順)")
    args = parser.parse_args()

    passphrase = os.getenv("MOBILE_DASHBOARD_PASSWORD")
    if not passphrase:
        raise SystemExit(
            "MOBILE_DASHBOARD_PASSWORD が設定されていません。.env に追加してください"
            "(モバイル側の閲覧パスワードとして使われます)。"
        )

    if not OUTPUT_DIR.exists():
        raise SystemExit(f"{OUTPUT_DIR}/ が見つかりません。先に screen.py を実行してください。")

    reports = sorted(
        (p for p in OUTPUT_DIR.glob("report_*.json") if REPORT_RE.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )[: args.keep]

    if not reports:
        raise SystemExit(f"{OUTPUT_DIR}/ に report_*.json が見つかりません。")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    manifest_entries = []
    keep_filenames = set()

    for path in reports:
        ts = REPORT_RE.match(path.name).group(1)
        snapshot = json.loads(path.read_text(encoding="utf-8"))

        enc_filename = f"{ts}.json.enc"
        keep_filenames.add(enc_filename)
        encrypted = encrypt_json(snapshot, passphrase)
        (REPORTS_DIR / enc_filename).write_text(
            json.dumps(encrypted), encoding="utf-8"
        )

        meta = snapshot.get("meta", {})
        candidates = snapshot.get("candidates", [])
        manifest_entries.append(
            {
                "ts": ts,
                "file": enc_filename,
                "generated_at": meta.get("generated_at"),
                "market": meta.get("market"),
                "universe": meta.get("universe"),
                "sector_first": meta.get("sector_first"),
                "top_sectors": meta.get("top_sectors"),
                "evaluable": len(candidates),
                "excluded": len(snapshot.get("excluded", [])),
                "top": _top_preview(candidates),
            }
        )

    manifest_entries.sort(key=lambda e: e["ts"], reverse=True)
    manifest_encrypted = encrypt_json({"reports": manifest_entries}, passphrase)
    (REPORTS_DIR / "manifest.enc").write_text(
        json.dumps(manifest_encrypted), encoding="utf-8"
    )

    # keep対象から外れた古い.encファイルを掃除
    removed = 0
    for existing in REPORTS_DIR.glob("*.json.enc"):
        if existing.name not in keep_filenames:
            existing.unlink()
            removed += 1

    print(f"{len(reports)}件のレポートを暗号化して {REPORTS_DIR}/ に同期しました。")
    if removed:
        print(f"対象外になった古いレポート{removed}件を削除しました。")
    print("反映するには docs/ を含めて git commit & push してください。")


if __name__ == "__main__":
    main()
