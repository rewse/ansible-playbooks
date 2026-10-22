"""Find the UniFi firewall policies that let the internet reach a web port.

The policies are the documented API's firewall/policies objects, and the port
lists are its traffic-matching-lists objects. Apache listens on TCP 80 and 443
only, so a policy matters when it admits new TCP connections to either port
over IPv6, whether it names IPv6 alone or both IP versions.
"""

from __future__ import annotations

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


def _item_ports(item: dict[str, Any], candidates: frozenset[int]) -> set[int]:
    if item.get("type") == "PORT_NUMBER":
        return {port for port in candidates if item.get("value") == port}
    if item.get("type") == "PORT_NUMBER_RANGE":
        return {
            port
            for port in candidates
            if item.get("start", 0) <= port <= item.get("stop", -1)
        }
    # An item of an unknown kind may cover anything.
    return set(candidates)


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
    named = set().union(*(_item_ports(item, WEB_PORTS) for item in items))
    return set(WEB_PORTS) - named if port_filter.get("matchOpposite") else named


def _admits_tcp(policy: dict[str, Any]) -> bool:
    protocol = (policy.get("ipProtocolScope") or {}).get("protocolFilter")
    if not protocol:
        return True
    kind = protocol.get("type")
    if kind == "PRESET":
        return (protocol.get("preset") or {}).get("name") == "TCP_UDP"
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


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {"udm_web_allows": udm_web_allows, "udm_web_only": udm_web_only}
