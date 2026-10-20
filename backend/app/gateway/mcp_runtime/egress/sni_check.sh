#!/bin/sh
# Squid external ACL for the egress sidecar (Feature 006, #59): OK only when
# the TLS server name the client sent (SNI) equals the CONNECT host, after the
# same normalisation (lower-case, one trailing dot dropped). No SNI ("-") or
# any other name: ERR, and the tunnel is terminated.
while read -r sni dst rest; do
  s=$(printf '%s' "$sni" | tr 'A-Z' 'a-z'); s=${s%.}
  d=$(printf '%s' "$dst" | tr 'A-Z' 'a-z'); d=${d%.}
  if [ -n "$s" ] && [ "$s" != "-" ] && [ "$s" = "$d" ]; then
    echo OK
  else
    echo ERR
  fi
done
