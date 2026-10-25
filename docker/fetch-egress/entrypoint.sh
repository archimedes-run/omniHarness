#!/bin/sh
# Fetch egress (public internet only) on the sandbox-egress image: the same
# pinned Squid and dnsmasq, a different config, no TLS interception.
# 1. The networks this container is attached to are written to two ACL files:
#    refused as destinations, and the only clients accepted
#    (FETCH_EGRESS_CLIENTS overrides the clients, space-separated CIDRs).
# 2. dnsmasq with stop-dns-rebind (no localhost exception) as Squid's only
#    resolver, forwarding to FETCH_EGRESS_DNS (Docker's resolver by default).
# 3. Squid.
set -eu
RUN=/run/fetch
mkdir -p "$RUN"
ip -o addr show scope global | awk '{print $4}' | while read -r cidr; do
  case "$cidr" in
    *:*) echo "$cidr" ;;
    *) ipcalc -n -p "$cidr" | awk -F= '{v[$1]=$2} END {print v["NETWORK"] "/" v["PREFIX"]}' ;;
  esac
done > "$RUN/attached.acl"
if [ ! -s "$RUN/attached.acl" ]; then
  echo "[fetch-egress] no global address on any interface; refusing to start" >&2
  exit 1
fi
if [ -n "${FETCH_EGRESS_CLIENTS:-}" ]; then
  printf '%s\n' $FETCH_EGRESS_CLIENTS > "$RUN/clients.acl"
else
  cp "$RUN/attached.acl" "$RUN/clients.acl"
fi
touch "$RUN/access.log" "$RUN/cache.log"
chown -R squid:squid "$RUN"
printf 'no-resolv\nno-hosts\ncache-size=0\nlisten-address=127.0.0.1\nbind-interfaces\nstop-dns-rebind\nserver=%s\n' "${FETCH_EGRESS_DNS:-127.0.0.11}" > "$RUN/dnsmasq.conf"
dnsmasq --conf-file="$RUN/dnsmasq.conf"
echo "[fetch-egress] proxy on :3128; attached: $(tr '\n' ' ' < "$RUN/attached.acl")" >&2
tail -n +1 -F "$RUN/access.log" "$RUN/cache.log" 2>/dev/null &
exec squid -N -f /opt/fetch/squid.conf
