#!/bin/sh
# Egress sidecar entrypoint (Feature 006, #59). Runs as the squid user.
# 1. wait for the gateway to hand over squid.conf, dnsmasq.conf and passwd
#    (0400 files on the /run/omni tmpfs, delivered over docker exec stdin);
# 2. find this container's address on OUTER_SUBNET (the endpoint listens
#    there only; the forward proxy's internal address is fixed in squid.conf);
# 3. start dnsmasq (Squid's only resolver), then Squid in the foreground.
set -eu
RUN=/run/omni
n=0
while [ ! -e "$RUN/ready" ]; do
  n=$((n + 1))
  if [ "$n" -gt 600 ]; then echo "[egress] the gateway never handed over the config" >&2; exit 3; fi
  sleep 0.05
done
OUTER_IP=""
for cidr in $(ip -o -4 addr show | awk '{print $4}'); do
  net=$(ipcalc -n "$cidr" | cut -d= -f2)
  if [ "$net/${cidr#*/}" = "${OUTER_SUBNET:-none}" ]; then
    if [ -n "$OUTER_IP" ]; then echo "[egress] more than one address on $OUTER_SUBNET" >&2; exit 4; fi
    OUTER_IP=${cidr%/*}
  fi
done
if [ -z "$OUTER_IP" ]; then echo "[egress] no address on OUTER_SUBNET=${OUTER_SUBNET:-unset}" >&2; exit 4; fi
umask 077
sed "s/@OUTER_IP@/$OUTER_IP/g" "$RUN/squid.conf" > /tmp/squid.conf
# Squid needs a certificate on an ssl-bump port even though it only peeks and
# splices (TLS is never decrypted); this one is never presented.
openssl req -x509 -newkey rsa:2048 -nodes -subj /CN=omni-egress-never-presented -days 2 \
  -keyout /tmp/never.key -out /tmp/never.crt >/dev/null 2>&1
cat /tmp/never.crt /tmp/never.key > /tmp/never-presented.pem
dnsmasq --conf-file="$RUN/dnsmasq.conf"
echo "[egress] endpoint on $OUTER_IP:8080" >&2
exec squid -N -f /tmp/squid.conf
