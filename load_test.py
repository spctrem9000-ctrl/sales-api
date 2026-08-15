import asyncio
import aiohttp
import time
import os
import json
import sqlite3
import base64
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad
import random
from datetime import datetime

# Encryption logic (mimicking desktop-agent)
ENCRYPTION_KEY = b"b3A2j8v9F1s4kL7w2q5P0xN4c8m3V6z9"

def encrypt_payload(payload_dict):
    iv = os.urandom(16)
    cipher = AES.new(ENCRYPTION_KEY, AES.MODE_CBC, iv)
    json_str = json.dumps(payload_dict)
    padded_data = pad(json_str.encode('utf-8'), AES.block_size)
    encrypted_bytes = cipher.encrypt(padded_data)
    combined = iv + encrypted_bytes
    return base64.b64encode(combined).decode('utf-8')

# Ensure API Key and Company exist
db_path = "sales_monitor.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT id FROM companies WHERE api_key = 'test_700_key'")
row = c.fetchone()
if not row:
    c.execute("INSERT INTO companies (name, api_key, is_active, auto_remind) VALUES ('Load Test Corp', 'test_700_key', 1, 1)")
    conn.commit()
conn.close()

async def send_sync(session, branch_idx):
    payload = {
        "branch_name": f"Branch_{branch_idx}",
        "day_id": random.randint(1000, 9999),
        "gross_total": 5000.0,
        "disc_value": 0.0,
        "disc_lines_value": 0.0,
        "net_total": round(random.uniform(1000, 5000), 2),
        "visa_total": 1000.0,
        "takeaway_count": 10,
        "takeaway_total": 500.0,
        "delivery_count": 5,
        "delivery_total": 200.0,
        "dlv_service_total": 50.0,
        "order_count": random.randint(50, 200),
        "business_date": datetime.now().strftime("%Y-%m-%d"),
        "metrics_json": {
            "top_sellers": {"Burger": 10, "Fries": 20},
            "refund_lines_count": 0,
            "refund_lines_total": 0,
            "top_invoices": [],
            "hourly_sales": {"10:00 AM": 500.0, "11:00 AM": 700.0}
        }
    }
    
    encrypted_str = encrypt_payload(payload)
    request_body = json.dumps({"payload": encrypted_str})
    
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": "test_700_key"
    }
    
    start_t = time.time()
    try:
        async with session.post("http://127.0.0.1:8000/api/sync/", data=request_body, headers=headers) as resp:
            status = resp.status
            text = await resp.text()
            if status != 200 and branch_idx == 1:
                print(f"Error {status}: {text}")
            end_t = time.time()
            return status, (end_t - start_t)
    except Exception as e:
        return 500, time.time() - start_t

async def main():
    print("🚀 Starting Load Test for 700 concurrent branches...")
    
    num_requests = 700
    connector = aiohttp.TCPConnector(limit=800) # Allow high concurrency
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for i in range(1, num_requests + 1):
            tasks.append(send_sync(session, i))
            
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        end_time = time.time()
        
        total_time = end_time - start_time
        successes = sum(1 for r in results if r[0] == 200)
        failures = num_requests - successes
        
        print("\n--- 📊 Load Test Results ---")
        print(f"Total Requests: {num_requests}")
        print(f"Successful: {successes}")
        print(f"Failed: {failures}")
        print(f"Total Time Taken: {total_time:.2f} seconds")
        if total_time > 0:
            print(f"Requests per Second: {num_requests / total_time:.2f} req/s")
        
        # Calculate average response time
        avg_resp_time = sum(r[1] for r in results) / num_requests
        print(f"Average Response Time: {avg_resp_time:.4f} seconds/req")

if __name__ == "__main__":
    asyncio.run(main())
