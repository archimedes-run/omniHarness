"""The built-in web fetcher behind the ``web_fetch`` tool.

It GETs a page through the fetch egress proxy (docker/fetch-egress, public
internet only), stops reading at 2 MB and 15 s, and extracts readable markdown
with trafilatura. ``guard`` checks every URL, and every redirect hop, before it
is requested; the proxy checks the addresses it actually connects to.
"""
