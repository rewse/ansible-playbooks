"""Find the UniFi firewall policies that let the internet reach a web port.

The policies are the documented API's firewall/policies objects, and the port
lists are its traffic-matching-lists objects. Apache listens on TCP 80 and 443
only, so a policy matters when it admits new TCP connections to either port
over IPv6, whether it names IPv6 alone or both IP versions. The forwards are
the legacy rest/portforward objects, which carry IPv4 from the WAN.

Every test errs towards exposure: a protocol, port item, or port field this
module cannot read counts as admitting TCP to both web ports, so an object of a
form it does not know is reported rather than passed over.
"""

from __future__ import annotations

import re
from typing import Any

WEB_PORTS = frozenset({80, 443})
TCP_PROTOCOL_NUMBER = 6


def _port_items(
    port_filter: dict[str, Any], lists: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """Returns the filter's port items, or None when they cannot be resolved."""
    if port_filter.get("type") == "PORTS":
        return port_filter.get("items") or []
    if port_filter.get("type") == "TRAFFIC_MATCHING_LIST":
        for entry in lists:
            if entry.get("id") == port_filter.get("trafficMatchingListId"):
                return entry.get("items") or []
    return None


def _is_port(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _item_ports(item: dict[str, Any]) -> set[int] | None:
    """Returns the web ports an item names, or None when it cannot be read."""
    if item.get("type") == "PORT_NUMBER" and _is_port(item.get("value")):
        return {port for port in WEB_PORTS if item["value"] == port}
    if (
        item.get("type") == "PORT_NUMBER_RANGE"
        and _is_port(item.get("start"))
        and _is_port(item.get("stop"))
    ):
        return {port for port in WEB_PORTS if item["start"] <= port <= item["stop"]}
    return None


def _admitted_web_ports(
    policy: dict[str, Any], lists: list[dict[str, Any]]
) -> set[int]:
    port_filter = (
        (policy.get("destination") or {}).get("trafficFilter", {}).get("portFilter")
    )
    if not port_filter:
        return set(WEB_PORTS)
    items = _port_items(port_filter, lists)
    if items is None:
        return set(WEB_PORTS)
    named = [_item_ports(item) for item in items]
    # An item that cannot be read may name either web port, so it counts as
    # admitting both, whether the filter selects the ports it names or every
    # port but those.
    if any(ports is None for ports in named):
        return set(WEB_PORTS)
    union = set().union(*(ports for ports in named if ports is not None))
    return set(WEB_PORTS) - union if port_filter.get("matchOpposite") else union


def _admits_tcp(policy: dict[str, Any]) -> bool:
    protocol = (policy.get("ipProtocolScope") or {}).get("protocolFilter")
    if not protocol:
        return True
    kind = protocol.get("type")
    # A preset other than TCP_UDP may include TCP too, so every preset counts.
    if kind == "PRESET":
        return True
    if kind == "NAMED_PROTOCOL":
        matches = (protocol.get("protocol") or {}).get("name") == "TCP"
    elif kind == "PROTOCOL_NUMBER":
        matches = protocol.get("protocolNumber") == TCP_PROTOCOL_NUMBER
    else:
        return True
    return matches != bool(protocol.get("matchOpposite"))


def _admits_new_connections(policy: dict[str, Any]) -> bool:
    states = policy.get("connectionStateFilter")
    return not states or "NEW" in states


def _admits_ipv6(policy: dict[str, Any]) -> bool:
    version = (policy.get("ipProtocolScope") or {}).get("ipVersion")
    return version != "IPV4"


def udm_web_allows(
    policies: list[dict[str, Any]], lists: list[dict[str, Any]], zone_id: str
) -> list[dict[str, Any]]:
    """Enabled ALLOW policies from the zone that admit IPv6 to TCP 80 or 443."""
    return [
        policy
        for policy in policies
        if (policy.get("action") or {}).get("type") == "ALLOW"
        and policy.get("enabled", True) is not False
        and (policy.get("source") or {}).get("zoneId") == zone_id
        and _admits_ipv6(policy)
        and _admits_tcp(policy)
        and _admits_new_connections(policy)
        and _admitted_web_ports(policy, lists)
    ]


def udm_web_only(
    policies: list[dict[str, Any]], lists: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The user-defined policies whose destination ports are all web ports.

    Removing one of these closes only web ports. A policy that also names
    another port, a range, or every port but some is left for a person to split.
    """
    selected = []
    for policy in policies:
        if (policy.get("metadata") or {}).get("origin") != "USER_DEFINED":
            continue
        port_filter = (
            (policy.get("destination") or {}).get("trafficFilter", {}).get("portFilter")
        )
        if not port_filter or port_filter.get("matchOpposite"):
            continue
        items = _port_items(port_filter, lists)
        if items and all(
            item.get("type") == "PORT_NUMBER" and item.get("value") in WEB_PORTS
            for item in items
        ):
            selected.append(policy)
    return selected


def _forward_ports(value: Any) -> set[int] | None:
    """Returns the web ports a forward's port field names, or None if unread.

    The field holds one port, a range such as 1000-2000, or a comma-separated
    list of either.
    """
    if _is_port(value):
        value = str(value)
    if not isinstance(value, str) or not value.strip():
        return None
    ports: set[int] = set()
    for part in value.split(","):
        bounds = re.fullmatch(r"(\d+)(?:-(\d+))?", part.strip(), re.ASCII)
        if not bounds:
            return None
        low, high = int(bounds[1]), int(bounds[2] or bounds[1])
        if low > high:
            return None
        ports |= {port for port in WEB_PORTS if low <= port <= high}
    return ports


def _forwards_to_web_port(forward: dict[str, Any]) -> bool:
    wan = _forward_ports(forward.get("dst_port"))
    # A forward without fwd_port keeps the WAN port.
    lan = _forward_ports(forward.get("fwd_port") or forward.get("dst_port"))
    return wan is None or lan is None or bool(wan | lan)


def udm_web_forwards(forwards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enabled forwards that may carry TCP to port 80 or 443.

    A forward counts when its WAN port or its forwarded port is a web port,
    whether named alone, in a range, or in a list, because either way the
    internet reaches a web server through it.
    """
    return [
        forward
        for forward in forwards
        if forward.get("enabled", True) is not False
        and forward.get("proto") != "udp"
        and _forwards_to_web_port(forward)
    ]


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "udm_web_allows": udm_web_allows,
            "udm_web_forwards": udm_web_forwards,
            "udm_web_only": udm_web_only,
        }
