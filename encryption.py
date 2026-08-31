import base64
import os
import json
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from fastapi import Request, Response
from fastapi.routing import APIRoute
from typing import Callable

from Crypto.Random import get_random_bytes

# 32 bytes key — MUST be set in environment
_aes_key_str = os.getenv("AES_KEY")
if not _aes_key_str:
    raise ValueError("AES_KEY environment variable must be set! (32 bytes)")
AES_KEY = _aes_key_str.encode("utf-8")

def encrypt_payload(data: dict) -> str:
    json_str = json.dumps(data)
    iv = get_random_bytes(16)
    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)
    padded_data = pad(json_str.encode("utf-8"), AES.block_size)
    encrypted_bytes = cipher.encrypt(padded_data)
    # Prepend IV to ciphertext
    return base64.b64encode(iv + encrypted_bytes).decode("utf-8")

def decrypt_payload(encrypted_b64: str) -> dict:
    raw_data = base64.b64decode(encrypted_b64)
    # Extract IV from the first 16 bytes
    iv = raw_data[:16]
    encrypted_bytes = raw_data[16:]
    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)
    decrypted_padded = cipher.decrypt(encrypted_bytes)
    decrypted_bytes = unpad(decrypted_padded, AES.block_size)
    return json.loads(decrypted_bytes.decode("utf-8"))

class EncryptedRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            # 1. Decrypt request body if "payload" is present
            if request.method in ("POST", "PUT"):
                try:
                    body_bytes = await request.body()
                    if body_bytes:
                        body_json = json.loads(body_bytes)
                        if "payload" in body_json:
                            decrypted = decrypt_payload(body_json["payload"])
                            # Mock the request's receive method so FastAPI parses the decrypted body
                            decrypted_bytes = json.dumps(decrypted).encode("utf-8")
                            request._body = decrypted_bytes
                            async def receive():
                                return {"type": "http.request", "body": decrypted_bytes}
                            request._receive = receive
                except Exception as e:
                    print(f"Decryption error: {e}")
            
            # 2. Call original handler
            response: Response = await original_route_handler(request)
            
            # 3. Encrypt response body if JSON
            if response.headers.get("content-type", "").startswith("application/json"):
                if hasattr(response, "body"):
                    try:
                        resp_json = json.loads(response.body)
                        # We don't want to double encrypt if it's already got payload (e.g. custom error)
                        if "payload" not in resp_json:
                            encrypted_str = encrypt_payload(resp_json)
                            response.body = json.dumps({"payload": encrypted_str}).encode("utf-8")
                            response.headers["content-length"] = str(len(response.body))
                    except Exception as e:
                        print(f"Encryption error: {e}")
            
            return response

        return custom_route_handler
