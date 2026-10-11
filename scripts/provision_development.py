"""Provision approved free development project; secrets only in Infisical/memory."""
import json
import os
import secrets
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cloud_setup import request_json

PROJECT = 'bde1d1c7-150c-4490-a43f-61ff9b6c6aae'
ORG = 'hwujoreceayygzaajktm'
NAME = 'palm-analysis-development'


def vault(name, value=None):
    base = 'https://app.infisical.com/api/v4/secrets/' + name
    headers = {'Authorization': 'Bearer ' + os.environ['INFISICAL_TOKEN'], 'Content-Type': 'application/json'}
    try:
        with urlopen(Request(base + '?projectId=' + PROJECT + '&environment=dev&secretPath=%2F&type=shared', headers=headers), timeout=30) as response:
            old = json.load(response)['secret']['secretValue']
        if value is not None and old != value:
            raise RuntimeError('Existing secret differs; no overwrite')
        return old
    except HTTPError as error:
        if error.code != 404:
            raise
    if value is None:
        return None
    body = {'projectId': PROJECT, 'environment': 'dev', 'secretPath': '/', 'type': 'shared', 'secretValue': value}
    with urlopen(Request(base, data=json.dumps(body).encode(), headers=headers, method='POST'), timeout=30) as response:
        json.load(response)
    if vault(name) != value:
        raise RuntimeError('Secret readback failed')
    return value


def main():
    token = os.environ['Supabase_access_token']
    org = request_json('https://api.supabase.com/v1/organizations/' + ORG, token)
    if org.get('plan') != 'free':
        raise RuntimeError('Free plan not verified')
    projects = request_json('https://api.supabase.com/v1/projects', token)
    matches = [p for p in projects if p.get('name') == NAME and p.get('organization_id') == org.get('id')]
    if len(matches) > 1:
        raise RuntimeError('Ambiguous development project')
    if matches:
        development = matches[0]
    else:
        if sum(p.get('status') != 'INACTIVE' for p in projects) >= 2:
            raise RuntimeError('Free project quota not available')
        password = vault('PALM_DEV_DB_PASSWORD')
        if not password:
            password = vault('PALM_DEV_DB_PASSWORD', secrets.token_urlsafe(40))
        development = request_json('https://api.supabase.com/v1/projects', token, {
            'name': NAME, 'organization_slug': ORG, 'db_pass': password,
            'region': 'ap-northeast-1',
        })
    ref = development.get('id')
    if not ref or ref == 'pyugqoogcoynvywihgym':
        raise RuntimeError('Invalid development project identity')
    vault('PALM_DEV_PROJECT_REF', ref)
    vault('PALM_DEV_SUPABASE_URL', 'https://' + ref + '.supabase.co')
    print(json.dumps({'development_project': NAME, 'ref': ref, 'status': development.get('status'), 'free_org_verified': True, 'credentials_stored_in_infisical': True, 'schema_applied': False}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Development provisioning stopped; no existing resource deleted; credentials suppressed.')
        raise SystemExit(1) from None
