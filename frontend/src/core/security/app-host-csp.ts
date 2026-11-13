import { contentSecurityPolicy } from "./page-csp";

/** A Host header we will put in a policy: a name or IPv4/IPv6, an optional port. */
const HOST =
  /^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*|\[[0-9A-Fa-f:.]+\])(?::\d{1,5})?$/;

/**
 * Spec 011 FR-017/FR-018 (M1): the Apps pages' policy. frame-src is this
 * origin's /api/apps/ only, never bare 'self': a frame that navigates itself
 * can reach app documents (each starts with the shim, so the host notices)
 * and nothing else on this origin. An `http://` source also matches the same
 * host over https. A Host header that is not a plain host[:port] frames
 * nothing at all.
 */
export function appHostPolicy(host: string | null): string {
  const frameSrc =
    host && HOST.test(host) ? `http://${host}/api/apps/` : "'none'";
  return contentSecurityPolicy({ frameSrc });
}
