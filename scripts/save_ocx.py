"""Store the existing Notch VM data credential in approved project secrets only."""
import ctypes
import json
import os
from ctypes import wintypes
from urllib.request import Request, urlopen

from provision_development import vault


class Credential(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR),
    ]


def read_credential(name):
    adv = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
    adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    adv.CredReadW.restype = wintypes.BOOL
    adv.CredFree.argtypes = [ctypes.c_void_p]
    pointer = ctypes.POINTER(Credential)()
    if not adv.CredReadW(name, 1, 0, ctypes.byref(pointer)):
        raise RuntimeError('Existing credential unavailable')
    try:
        item = pointer.contents
        return item.UserName, ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize).decode('utf-8')
    finally:
        adv.CredFree(pointer)


def main():
    if os.name != 'nt':
        raise RuntimeError('This bootstrap requires the existing Windows credential store')
    origin, _ = read_credential('OCX Notch:remote-connection')
    saved_origin, data_origin = read_credential('OCX Notch:remote-data-origin')
    if saved_origin != origin or origin != 'https://ocx.aura-board.com' or data_origin != 'http://100.120.114.62:10100':
        raise RuntimeError('Selected VM connection differs; inspect before saving')
    _, encoded = read_credential('OCX Notch:codex-data:' + origin)
    key = json.loads(encoded)['key']
    request = Request(data_origin + '/v1/models', headers={'X-OpenCodex-API-Key': key})
    with urlopen(request, timeout=20) as response:
        models = json.load(response)
    if not any(model.get('id') == 'gpt-6.1-sol' for model in models.get('data', [])):
        raise RuntimeError('Selected model unavailable')
    vault('PALM_OCX_BASE_URL', data_origin)
    vault('PALM_OCX_API_KEY', key)
    vault('PALM_OCX_MODEL', 'gpt-6.1-sol')
    print('Existing VM OCX data credential saved and read back in Infisical; no key created or rotated.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('OCX credential save stopped; credentials suppressed.')
        raise SystemExit(1) from None
