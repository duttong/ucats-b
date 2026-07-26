# network/

Host-level network config for `ucatsb`, provisioned by hand on the Pi (not
installed by `setup.sh`). Kept here for version control, same rationale as
`desktop/` for the `.desktop` launchers.

## 99-eth1-gateway

NetworkManager dispatcher script. Re-adds the default route via
`10.11.96.1 dev eth1` (the aircraft router) if it's ever missing when `eth1`
comes up. Written after a 2026-07-24 incident where the Pi had a valid static
IP on `eth1` but no default route, killing the satellite/ground telemetry
uplink until fixed by hand — root cause still being tracked down (see
CLAUDE.md's "Host access" section).

This script is a safety net, not the primary fix. The primary fix is making
sure `eth1`'s NetworkManager connection profile has `ipv4.gateway` set
persistently:

```
nmcli connection show                      # find the eth1 profile name
nmcli connection show <profile-name>        # check ipv4.gateway
nmcli connection modify <profile-name> ipv4.gateway 10.11.96.1
nmcli connection up <profile-name>
```

**Deployed on ucatsb 2026-07-26.** The `eth1` profile is `USB2-Ethernet`;
it also had `ipv4.never-default: yes` set, which would have blocked NM from
ever installing the gateway as the default route even with `ipv4.gateway`
set — that had to be cleared too:

```
sudo nmcli connection modify USB2-Ethernet ipv4.gateway 10.11.96.1 ipv4.never-default no
```

`USB2-Ethernet` is `autoconnect: yes` with unlimited retries and a `manual`
(static) IPv4 method, so it activates as soon as `eth1` gets carrier —
whichever powers on first, ucatsb or the aircraft router. Confirmed after
`nmcli connection up USB2-Ethernet`: `default via 10.11.96.1 dev eth1 metric
100`, correctly preferred over WiFi's `metric 600` default route.

Install the dispatcher script on the Pi:

```
sudo cp 99-eth1-gateway /etc/NetworkManager/dispatcher.d/99-eth1-gateway
sudo chown root:root /etc/NetworkManager/dispatcher.d/99-eth1-gateway
sudo chmod 0755 /etc/NetworkManager/dispatcher.d/99-eth1-gateway
```

NetworkManager only runs dispatcher scripts owned by root and not
group/other-writable, so ownership and permissions matter, not just the copy.
**Also deployed on ucatsb 2026-07-26** — verified it runs clean (exit 0) as
the backstop, though with the profile fix above it wasn't actually needed
to add the route (NM installed it directly from the persistent gateway
setting).

Check it fired (or didn't need to) via:

```
journalctl -t network-eth1-gateway
```
