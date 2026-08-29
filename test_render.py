import requests
from encryption import decrypt_payload

try:
    login_data = {'username': 'super_admin', 'password': 'Kareemsobhy@20'}
    r1 = requests.post('https://sales-api-ngdi.onrender.com/api/auth/login', json=login_data)
    if r1.status_code == 200:
        token_data = decrypt_payload(r1.json()['payload'])
        token = token_data['access_token']
        print('Logged in')
        
        r2 = requests.get('https://sales-api-ngdi.onrender.com/api/dashboard', headers={'Authorization': f'Bearer {token}'})
        data = decrypt_payload(r2.json()['payload'])
        for b in data.get('branches', []):
            metrics = b.get('metrics', {})
            print(f"{b['branch_name']}: lines {metrics.get('refund_lines_count')}, inv {metrics.get('refund_invoices_count')}")
    else:
        print('Login failed', r1.text)
except Exception as e:
    print(e)
