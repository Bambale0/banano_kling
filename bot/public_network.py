"""Shared fail-closed public-unicast address classification for media fetches."""
import ipaddress


def is_public_unicast(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.strip().strip("[]"))
    except (AttributeError, ValueError):
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return bool(address.is_global and not (
        address.is_multicast or address.is_unspecified or address.is_reserved
        or address.is_link_local or address.is_loopback or address.is_private
    ))
