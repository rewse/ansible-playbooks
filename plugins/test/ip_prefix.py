"""Test whether a value is one canonical IP network no broader than a minimum.

Prefixes fetched from a feed are written into Apache, fail2ban and firewall
configuration, where a stray character can change the meaning of the line and
a very short prefix trusts a large part of the internet. A value passes only
when it is a string in the exact form ipaddress prints for that network:
lowercase hex, no leading zeros, no host bits, no surrounding whitespace.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

DOCUMENTATION = r"""
name: ip_prefix
short_description: Test for one canonical IP network with a minimum prefix length
description:
  - True when the value is a string such as C(130.176.0.0/18) that names one
    IPv4 or IPv6 network exactly as Python's ipaddress module prints it, and
    whose prefix length is at least the minimum for its IP version.
positional: min_ipv4_prefixlen, min_ipv6_prefixlen
options:
  min_ipv4_prefixlen:
    description: Shortest IPv4 prefix length accepted.
    type: int
    required: true
  min_ipv6_prefixlen:
    description: Shortest IPv6 prefix length accepted.
    type: int
    required: true
"""

EXAMPLES = r"""
- name: Check prefixes
  ansible.builtin.assert:
    that:
      - prefixes | reject('ip_prefix', 8, 24) | list | length == 0
"""

RETURN = r"""
_value:
  description: Whether the value is an accepted network.
  type: bool
"""

_FORM = re.compile(r"[0-9a-f.:]+/[0-9]{1,3}")


def ip_prefix(value: Any, min_ipv4_prefixlen: int, min_ipv6_prefixlen: int) -> bool:
    if not isinstance(value, str) or not _FORM.fullmatch(value):
        return False
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError:
        return False
    if str(network) != value:
        return False
    minimum = min_ipv4_prefixlen if network.version == 4 else min_ipv6_prefixlen
    return network.prefixlen >= minimum


class TestModule:
    def tests(self) -> dict[str, Any]:
        return {"ip_prefix": ip_prefix}
