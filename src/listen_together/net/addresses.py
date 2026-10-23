import socket

try:
    import psutil
except ImportError:
    psutil = None


def list_local_ipv4_addresses() -> list[str]:
    if psutil is not None:
        discovered = {
            address.address
            for entries in psutil.net_if_addrs().values()
            for address in entries
            if address.family == socket.AF_INET
            and not address.address.startswith("127.")
            and not address.address.startswith("169.254.")
        }
        if discovered:
            return sorted(discovered)

    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        ):
            address = info[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            addresses.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass

    return sorted(addresses)


def best_local_ipv4() -> str:
    if psutil is not None:
        for interface_name, entries in psutil.net_if_addrs().items():
            if "radmin" not in interface_name.casefold():
                continue
            for address in entries:
                if address.family == socket.AF_INET and not address.address.startswith(
                    "127."
                ):
                    return address.address
    addresses = list_local_ipv4_addresses()
    radmin = [address for address in addresses if address.startswith("26.")]
    if radmin:
        return radmin[0]
    return addresses[0] if addresses else "127.0.0.1"

