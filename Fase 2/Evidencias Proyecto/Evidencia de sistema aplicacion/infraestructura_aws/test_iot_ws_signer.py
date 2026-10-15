import boto3
import hmac
import hashlib
import datetime
import urllib.parse

def get_iot_websocket_url(region="us-east-1", endpoint="a2ep4ljpgw7df7-ats.iot.us-east-1.amazonaws.com"):
    session = boto3.Session()
    creds = session.get_credentials().get_frozen_credentials()
    
    t = datetime.datetime.now(datetime.timezone.utc)
    date = t.strftime('%Y%m%d')
    amz_date = t.strftime('%Y%m%dT%H%M%SZ')
    
    service = 'iotdevicegateway'
    algorithm = 'AWS4-HMAC-SHA256'
    credential_scope = f'{date}/{region}/{service}/aws4_request'
    
    canonical_uri = '/mqtt'
    
    query_params = {
        'X-Amz-Algorithm': algorithm,
        'X-Amz-Credential': f'{creds.access_key}/{credential_scope}',
        'X-Amz-Date': amz_date,
        'X-Amz-SignedHeaders': 'host'
    }
    if creds.token:
        query_params['X-Amz-Security-Token'] = creds.token
        
    sorted_params = sorted(query_params.items())
    canonical_querystring = '&'.join([f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}" for k, v in sorted_params])
    canonical_headers = f'host:{endpoint}\n'
    signed_headers = 'host'
    payload_hash = hashlib.sha256(b'').hexdigest()
    
    canonical_request = f'GET\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}'
    string_to_sign = f'{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()}'
    
    def sign(key, msg):
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()
        
    k_date = sign(('AWS4' + creds.secret_key).encode('utf-8'), date)
    k_region = sign(k_date, region)
    k_service = sign(k_region, service)
    k_signing = sign(k_service, 'aws4_request')
    
    signature = hmac.new(k_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
    
    ws_url = f'wss://{endpoint}{canonical_uri}?{canonical_querystring}&X-Amz-Signature={signature}'
    return ws_url

if __name__ == '__main__':
    url = get_iot_websocket_url()
    print("URL length:", len(url))
    print("URL sample:", url[:90] + "...")
