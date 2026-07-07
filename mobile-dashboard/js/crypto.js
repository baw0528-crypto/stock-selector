/**
 * sync_report.py が書き出す暗号化フォーマット(PBKDF2-SHA256 + AES-256-GCM)を
 * ブラウザのWeb Crypto APIで復号するための最小ヘルパー。外部ライブラリ不使用。
 */

function base64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

/** passphraseで暗号化オブジェクト({salt,nonce,ciphertext,iterations})を復号し、JSONとして返す。
 *  パスフレーズが違う場合は例外(DOMException: OperationError)を投げる。 */
async function decryptPayload(passphrase, payload) {
  const enc = new TextEncoder();
  const salt = base64ToBytes(payload.salt);
  const nonce = base64ToBytes(payload.nonce);
  const ciphertext = base64ToBytes(payload.ciphertext);

  const baseKey = await crypto.subtle.importKey(
    "raw",
    enc.encode(passphrase),
    "PBKDF2",
    false,
    ["deriveKey"]
  );
  const key = await crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt,
      iterations: payload.iterations || 210000,
      hash: "SHA-256",
    },
    baseKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["decrypt"]
  );
  const plainBuf = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: nonce },
    key,
    ciphertext
  );
  return JSON.parse(new TextDecoder().decode(plainBuf));
}

async function fetchAndDecrypt(passphrase, url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${url} の取得に失敗しました (${res.status})`);
  const payload = await res.json();
  return decryptPayload(passphrase, payload);
}
