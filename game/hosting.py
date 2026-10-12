"""Explicit Host and same-origin validation for local and configured HTTPS hosting."""
import ipaddress
import re


def hostname(value):
    value = value.strip().lower()
    if value == '0.0.0.0':
        raise ValueError('Allow the actual LAN address, not 0.0.0.0.')
    try:
        if ipaddress.ip_address(value).version != 4:
            raise ValueError('Use an IPv4 address or a hostname.')
    except ValueError:
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', value) or ':' in value:
            raise ValueError('Allowed hosts must be hostnames or IPv4 addresses without a scheme or port.')
    return value


def authorities(port, allowed):
    result = set()
    for host in ('127.0.0.1', 'localhost', *allowed):
        host = hostname(host)
        result.add(f'{host}:{port}')
        if port == 80:
            result.add(host)
    return result
