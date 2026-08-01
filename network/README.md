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
whichever powers on first, ucatsb or the aircraft router.

Ethernet connections get a lower default NM route metric (100) than WiFi
(600), so the first version of this fix made `eth1`'s default route win
over `wlan0` unconditionally. That broke bench testing: on the bench,
`eth1` commonly has a ground-checkout laptop plugged into it (not the
aircraft router), which is enough to give it carrier and activate the
profile, but `10.11.96.1` isn't actually reachable through it. With that
route winning, all general IPv4 internet traffic (not just the `10.11.96.x`
subnet, which is a separate, unaffected route) silently failed instead of
falling back to WiFi — including a fresh NTP sync, since bench WiFi is the
one with real internet access (aircraft WiFi never has internet, per
CLAUDE.md's "Host access" section).

Fixed by giving `eth1`'s default route a *higher* metric than WiFi's, so
WiFi keeps winning whenever it's actually connected:

```
sudo nmcli connection modify USB2-Ethernet ipv4.route-metric 700
sudo nmcli connection up USB2-Ethernet
```

This is safe on the bench: WiFi (metric 600) wins for general traffic
regardless of what's plugged into `eth1`. Confirmed on ucatsb: with the
laptop on `eth1`, `ip route get 8.8.8.8` and a live ping/curl all correctly
went out via `wlan0`, while `eth1`'s default route and the `10.11.96.0/24`
subnet route remained present in the table (just deprioritized) for when
the aircraft router actually answers.

Metric alone isn't enough for flight, though: `wlan0` *does* get connected
in the air, to one of the onboard Aeris analyzers' own WiFi (`AerisUltra*`
SSIDs, saved profiles from occasionally checking instrument status over
VNC) — it's not idle the way "no ground WiFi in the air" first suggested.
Since those are ordinary DHCP connections (`ipv4.route-metric: -1`, i.e.
NM's default ~600), one of them winning a metric race against `eth1` was
still possible. `eth1` must always be the priority in flight, full stop,
so instead of relying on metric ordering here too, `ipv4.never-default` is
set to `yes` on all three `AerisUltra1001xx/1007xx/1013xx` profiles —
structurally prevents them from ever supplying the default route,
regardless of metric or of `eth1`'s state:

```
sudo nmcli connection modify AerisUltra100148 ipv4.never-default yes
sudo nmcli connection modify AerisUltra100740 ipv4.never-default yes
sudo nmcli connection modify AerisUltra101362 ipv4.never-default yes
```

Ground/lab networks (`ESPO-SARP1`, `ESPO`, `NOAA_Guest`, `NOAA_Secure`) are
left alone (`ipv4.never-default: no`) since WiFi should stay primary on the
bench when connected to one of those.

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
## To set the network gateway for Panama

These commands add a new route but does not remove the route set in Houston (10.16.101.0/24)

sudo nmcli connection modify "USB2-Ethernet" +ipv4.routes "10.16.103.0/24 10.11.96.1"
sudo nmcli connection up "USB2-Ethernet"