"""The tool names the MCP servers we ship config for ACTUALLY expose (007).

Read from each server's published package, not from the rules file — reading
the rules to decide what the rules should cover proves nothing, and the
Calendar bug was exactly a rules file written against names that never occur.

Unprefixed, as each server exposes them. After loading, langchain-mcp-adapters
names them `<server>_<tool>` (tool_name_prefix=True), with the server name from
extensions_config.json.

Sources (2026-10-20):
  * filesystem   @modelcontextprotocol/server-filesystem 2.0.0, dist/index.js registerTool(...)
  * github       @modelcontextprotocol/server-github 2025.4.8, dist/index.js tool list
  * postgres     @modelcontextprotocol/server-postgres 0.6.2
  * gmail        @gongrzhe/server-gmail-autoauth-mcp 1.1.11, dist/index.js
  * googlecalendar  @cocal/google-calendar-mcp 2.7.0, build/index.js tool registry + manage-accounts
  * session-watcher  backend/packages/session_watcher/session_watcher/server.py
  * github-issue-connector  listed from the running server on this installation
    (a server built with mcp_build; extensions/extensions_config.json)
"""

from __future__ import annotations

MCP_SERVER_TOOLS: dict[str, tuple[str, ...]] = {
    "filesystem": (
        "read_file",
        "read_text_file",
        "read_media_file",
        "read_multiple_files",
        "write_file",
        "edit_file",
        "create_directory",
        "list_directory",
        "list_directory_with_sizes",
        "directory_tree",
        "move_file",
        "search_files",
        "get_file_info",
        "list_allowed_directories",
    ),
    "github": (
        "create_or_update_file",
        "search_repositories",
        "create_repository",
        "get_file_contents",
        "push_files",
        "create_issue",
        "create_pull_request",
        "fork_repository",
        "create_branch",
        "list_commits",
        "list_issues",
        "update_issue",
        "add_issue_comment",
        "search_code",
        "search_issues",
        "search_users",
        "get_issue",
        "get_pull_request",
        "list_pull_requests",
        "create_pull_request_review",
        "merge_pull_request",
        "get_pull_request_files",
        "get_pull_request_status",
        "update_pull_request_branch",
        "get_pull_request_comments",
        "get_pull_request_reviews",
    ),
    "postgres": ("query",),
    "gmail": (
        "send_email",
        "draft_email",
        "read_email",
        "search_emails",
        "modify_email",
        "delete_email",
        "list_email_labels",
        "batch_modify_emails",
        "batch_delete_emails",
        "create_label",
        "update_label",
        "delete_label",
        "get_or_create_label",
        "create_filter",
        "list_filters",
        "get_filter",
        "delete_filter",
        "create_filter_from_template",
        "download_attachment",
    ),
    "googlecalendar": (
        "list-calendars",
        "list-events",
        "search-events",
        "get-event",
        "list-colors",
        "create-event",
        "create-events",
        "update-event",
        "delete-event",
        "get-freebusy",
        "get-current-time",
        "respond-to-event",
        "manage-accounts",
    ),
    "session-watcher": ("list_coding_sessions", "get_session_status"),
    "github-issue-connector": ("status", "get_rate_limit", "list_user_repos", "list_org_repos", "list_repo_issues", "get_issue", "search_issues"),
}

#: Removed from the surface by extensions_config (FR-012): never registered.
DENIED = frozenset({"gmail_send_email"})

#: Composio connector tools are fetched per user from Composio's API at run
#: time, so no package lists them. These are the ones a rule names, measured
#: from a live connection 2026-09-23 (default_rules.yaml, CONNECTOR TOOLS).
KNOWN_CONNECTOR_TOOLS: tuple[str, ...] = (
    "connector-gmail_GMAIL_FETCH_EMAILS",
    "connector-gmail_GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
    "connector-gmail_GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
    "connector-gmail_GMAIL_LIST_THREADS",
    "connector-gmail_GMAIL_LIST_LABELS",
    "connector-gmail_GMAIL_GET_PROFILE",
    "connector-gmail_GMAIL_GET_ATTACHMENT",
    "connector-gmail_GMAIL_CREATE_EMAIL_DRAFT",
    "connector-gmail_GMAIL_DELETE_MESSAGE",
    "connector-gmail_GMAIL_MOVE_TO_TRASH",
    "connector-googlecalendar_GOOGLECALENDAR_FIND_EVENT",
    "connector-googlecalendar_GOOGLECALENDAR_LIST_CALENDARS",
    "connector-googlecalendar_GOOGLECALENDAR_GET_CALENDAR",
    "connector-googlecalendar_GOOGLECALENDAR_FIND_FREE_SLOTS",
    "connector-googlecalendar_GOOGLECALENDAR_GET_CURRENT_DATE_TIME",
    "connector-googlecalendar_GOOGLECALENDAR_QUICK_ADD",
    "connector-googlecalendar_GOOGLECALENDAR_CREATE_EVENT",
    "connector-googlecalendar_GOOGLECALENDAR_UPDATE_EVENT",
    "connector-googlecalendar_GOOGLECALENDAR_DELETE_EVENT",
)

#: Built-in, config and middleware tools, by the name each tool object carries
#: (omniharness.tools.tools.registrable_tool_names lists them in production).
BUILTIN_TOOLS: tuple[str, ...] = (
    "web_search",
    "web_fetch",
    "image_search",
    "ls",
    "read_file",
    "glob",
    "grep",
    "write_file",
    "str_replace",
    "bash",
    "present_files",
    "ask_clarification",
    "preview",
    "mcp_build",
    "ledger_read",
    "ledger_apply",
    "task",
    "view_image",
    "tool_search",
    "skill_manage",
    "setup_agent",
    "update_agent",
    "write_todos",
)

MCP_TOOLS: tuple[str, ...] = tuple(f"{server}_{tool}" for server, tools in MCP_SERVER_TOOLS.items() for tool in tools)

ALL_REAL_TOOLS: tuple[str, ...] = BUILTIN_TOOLS + MCP_TOOLS + KNOWN_CONNECTOR_TOOLS
