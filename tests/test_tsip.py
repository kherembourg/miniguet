import unittest

import server

IFCONFIG = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
utun0: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1280
\tinet 100.96.0.4 --> 100.96.0.4 netmask 0xffffffff
utun5: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1280
\tinet 100.75.247.49 --> 100.75.247.49 netmask 0xffffffff
"""


class PickTailscaleIpTest(unittest.TestCase):
    def test_uses_interface_routing_tailscale_dns(self):
        # Cloudflare WARP also sits in 100.64/10 (utun0): take the interface that routes 100.100.100.100
        route = "   route to: 100.100.100.100\n  interface: utun5\n"
        self.assertEqual(server.pick_tailscale_ip(route, IFCONFIG), "100.75.247.49")

    def test_no_route_means_not_ready(self):
        self.assertIsNone(server.pick_tailscale_ip("route: writing to routing socket: not in table\n", IFCONFIG))


if __name__ == "__main__":
    unittest.main()
