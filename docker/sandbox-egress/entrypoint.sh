#!/bin/sh
# 1. A fresh CA for this run: key on tmpfs only (squid-readable), the
#    certificate copied to /ca-out for sandboxes to trust. Name constraints
#    limit it to the registries' domains (subtrees: their certificates carry
#    wildcards), so even its key cannot vouch for any other site.
# 2. dnsmasq (stop-dns-rebind) as Squid's only resolver, then Squid.
set -eu
RUN=/run/egress
mkdir -p "$RUN" /ca-out
umask 077
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=omni-harness sandbox egress" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "nameConstraints=critical,permitted;DNS:npmjs.org,permitted;DNS:pypi.org,permitted;DNS:pythonhosted.org" \
  -keyout "$RUN/ca.key" -out "$RUN/ca.crt" >/dev/null 2>&1
cat "$RUN/ca.crt" "$RUN/ca.key" > "$RUN/ca.pem"
rm -f "$RUN/ca.key"
umask 022
# World-readable: the sandbox's shell runs as an unprivileged user.
install -m 0644 "$RUN/ca.crt" /ca-out/ca.crt.tmp && mv /ca-out/ca.crt.tmp /ca-out/ca.crt
rm -rf "$RUN/ssl_db"
/usr/lib/squid/security_file_certgen -c -s "$RUN/ssl_db" -M 4MB >/dev/null
touch "$RUN/access.log" "$RUN/cache.log"
chown -R squid:squid "$RUN"
chmod 0400 "$RUN/ca.pem"
printf 'no-resolv\nno-hosts\ncache-size=0\nlisten-address=127.0.0.1\nbind-interfaces\nstop-dns-rebind\nrebind-localhost-ok\nserver=127.0.0.11\n' > "$RUN/dnsmasq.conf"
dnsmasq --conf-file="$RUN/dnsmasq.conf"
echo "[sandbox-egress] CA ready, proxy on :3128" >&2
# Squid writes its logs as the squid user; this (root) shell forwards them.
tail -n +1 -F "$RUN/access.log" "$RUN/cache.log" 2>/dev/null &
exec squid -N -f /etc/squid/sandbox-egress.conf
