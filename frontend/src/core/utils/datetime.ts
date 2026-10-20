import { formatDistanceToNow } from "date-fns";
import { enUS as dateFnsEnUS, zhCN as dateFnsZhCN } from "date-fns/locale";

import { detectLocale, type Locale } from "@/core/i18n";
import { getLocaleFromCookie } from "@/core/i18n/cookies";

function getDateFnsLocale(locale: Locale) {
  switch (locale) {
    case "zh-CN":
      return dateFnsZhCN;
    case "en-US":
    default:
      return dateFnsEnUS;
  }
}

/** An ISO date-time with no zone designator ("2026-10-19T16:00:00.123"). */
const ZONELESS_ISO = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;

/**
 * A backend timestamp as an instant. The backend writes every timestamp in
 * UTC, but a store can hand one back without its zone (SQLite drops it), and
 * `new Date()` reads a zone-less ISO string as LOCAL time: in New York a chat
 * updated a moment ago read "in about 4 hours". A zone-less string is UTC.
 */
export function parseTimestamp(date: Date | string | number): Date {
  if (typeof date === "string" && ZONELESS_ISO.test(date.trim())) {
    return new Date(`${date.trim().replace(" ", "T")}Z`);
  }
  return date instanceof Date ? date : new Date(date);
}

export function formatTimeAgo(date: Date | string | number, locale?: Locale) {
  const effectiveLocale =
    locale ??
    (getLocaleFromCookie() as Locale | null) ??
    // Fallback when cookie is missing (or on first render)
    detectLocale();
  return formatDistanceToNow(parseTimestamp(date), {
    addSuffix: true,
    locale: getDateFnsLocale(effectiveLocale),
  });
}
