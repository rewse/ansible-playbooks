#!/bin/sh

# Wait for dnsmasq to start
sleep 15

# Update IPv6 RA MTU to 9000
sed -i 's/ra-param=br0,mtu:1500/ra-param=br0,mtu:9000/' /run/dnsmasq.dhcp.conf.d/*_IPV6.conf

# Restart dnsmasq
killall -HUP dnsmasq

exit 0
