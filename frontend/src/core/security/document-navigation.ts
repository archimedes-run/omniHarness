/** These routes have a different document CSP; client routing cannot replace it. */
export function isAppsDocument(pathname: string): boolean {
  return (
    pathname === "/workspace/apps" || pathname.startsWith("/workspace/apps/")
  );
}

export function crossesDocumentPolicy(current: URL, destination: URL): boolean {
  return (
    current.origin === destination.origin &&
    isAppsDocument(current.pathname) !== isAppsDocument(destination.pathname)
  );
}

/** Preserve ordinary client routing within one document policy. */
export function navigateWorkspace(href: string, push: (href: string) => void) {
  const current = new URL(window.location.href);
  const destination = new URL(href, current);
  if (crossesDocumentPolicy(current, destination)) {
    window.location.assign(destination.href);
  } else {
    push(href);
  }
}

export interface DocumentClick {
  defaultPrevented: boolean;
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}

export interface DocumentClickAnchor {
  href: string;
  target: string;
  download: boolean;
}

/**
 * The destination for a click that must load a new document, or null when
 * the click is left to the browser or client routing.
 */
export function documentLoadTarget(
  click: DocumentClick,
  anchor: DocumentClickAnchor | null,
  currentHref: string,
): string | null {
  if (
    !anchor ||
    click.defaultPrevented ||
    click.button !== 0 ||
    click.metaKey ||
    click.ctrlKey ||
    click.shiftKey ||
    click.altKey ||
    anchor.download ||
    (anchor.target !== "" && anchor.target !== "_self")
  )
    return null;
  let current: URL;
  let destination: URL;
  try {
    current = new URL(currentHref);
    destination = new URL(anchor.href, current);
  } catch {
    return null;
  }
  return crossesDocumentPolicy(current, destination) ? destination.href : null;
}
