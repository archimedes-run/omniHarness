/**
 * Spec 011 FR-022/FR-023: validate one protocol message against
 * protocol.schema.json. The host page (core/apps/protocol.ts) imports this
 * file; scripts/build-app-shim.mjs inlines the SAME function into the
 * platform shim, so the two sides cannot drift.
 *
 * It must stay self-contained (no imports, nothing from module scope): the
 * build script copies its text.
 *
 * Returns {ok: true, type} or {ok: false, reason}. Reasons are short stable
 * codes (they are logged as app_message_refused and sent back to the frame):
 * not_an_object, not_json, too_large, unknown_type, missing_key:<k>,
 * unknown_key:<k>, bad_value:<k>.
 *
 * @param {any} schema the parsed protocol.schema.json
 * @param {"frame_to_host"|"frame_to_host_window"|"host_to_frame"} direction
 * @param {unknown} message
 * @returns {{ok: true, type: string} | {ok: false, reason: string}}
 */
export function validateProtocolMessage(schema, direction, message) {
  var OBJECT_PROTO = Object.getPrototypeOf({});
  var MAX_DEPTH = 32;
  var MAX_NODES = 20000;
  var nodes = 0;

  function isPlainObject(value) {
    if (value === null || typeof value !== "object") return false;
    if (Array.isArray(value)) return false;
    var proto = Object.getPrototypeOf(value);
    return proto === OBJECT_PROTO || proto === null;
  }

  // Plain JSON only: null, booleans, finite numbers, strings, arrays and
  // plain objects. No Dates, Maps, buffers, ports, blobs or cycles.
  function isPlainJson(value, depth) {
    nodes += 1;
    if (nodes > MAX_NODES || depth > MAX_DEPTH) return false;
    if (value === null) return true;
    var kind = typeof value;
    if (kind === "string" || kind === "boolean") return true;
    if (kind === "number") return isFinite(value);
    if (kind !== "object") return false;
    if (Array.isArray(value)) {
      if (Object.getPrototypeOf(value) !== Array.prototype) return false;
      for (var i = 0; i < value.length; i++) {
        if (!isPlainJson(value[i], depth + 1)) return false;
      }
      return true;
    }
    if (!isPlainObject(value)) return false;
    var keys = Object.keys(value);
    for (var k = 0; k < keys.length; k++) {
      if (!isPlainJson(value[keys[k]], depth + 1)) return false;
    }
    return true;
  }

  function utf8Length(text) {
    if (typeof TextEncoder !== "undefined") {
      return new TextEncoder().encode(text).length;
    }
    return unescape(encodeURIComponent(text)).length;
  }

  function typeMatches(want, value) {
    var list = Array.isArray(want) ? want : [want];
    for (var i = 0; i < list.length; i++) {
      var t = list[i];
      if (t === "null" && value === null) return true;
      if (t === "string" && typeof value === "string") return true;
      if (t === "boolean" && typeof value === "boolean") return true;
      if (
        t === "integer" &&
        typeof value === "number" &&
        Number.isInteger(value)
      )
        return true;
      if (t === "number" && typeof value === "number" && isFinite(value))
        return true;
    }
    return false;
  }

  function valueOk(rule, value) {
    if (rule.json === true) return true; // already checked as plain JSON
    if (Object.prototype.hasOwnProperty.call(rule, "const")) {
      return value === rule["const"];
    }
    if (rule["enum"]) return rule["enum"].indexOf(value) !== -1;
    if (rule.type !== undefined && !typeMatches(rule.type, value)) return false;
    if (typeof value === "string") {
      if (rule.minLength !== undefined && value.length < rule.minLength)
        return false;
      if (rule.maxLength !== undefined && value.length > rule.maxLength)
        return false;
      if (rule.pattern !== undefined && !new RegExp(rule.pattern).test(value))
        return false;
    }
    if (typeof value === "number") {
      if (rule.minimum !== undefined && value < rule.minimum) return false;
      if (rule.maximum !== undefined && value > rule.maximum) return false;
    }
    return true;
  }

  var table = schema && schema[direction];
  if (!table) return { ok: false, reason: "unknown_type" };
  if (!isPlainObject(message)) return { ok: false, reason: "not_an_object" };
  if (!isPlainJson(message, 0)) return { ok: false, reason: "not_json" };

  var limits = schema.limits || {};
  var max =
    direction === "host_to_frame"
      ? limits.host_to_frame_max_bytes
      : limits.frame_to_host_max_bytes;
  var text;
  try {
    text = JSON.stringify(message);
  } catch (_err) {
    return { ok: false, reason: "not_json" };
  }
  if (typeof max === "number" && utf8Length(text) > max) {
    return { ok: false, reason: "too_large" };
  }

  var type = message.type;
  if (
    typeof type !== "string" ||
    !Object.prototype.hasOwnProperty.call(table, type)
  ) {
    return { ok: false, reason: "unknown_type" };
  }
  var rules = table[type];
  var given = Object.keys(message);
  for (var g = 0; g < given.length; g++) {
    if (!Object.prototype.hasOwnProperty.call(rules, given[g])) {
      return { ok: false, reason: "unknown_key:" + given[g].slice(0, 32) };
    }
  }
  var names = Object.keys(rules);
  for (var n = 0; n < names.length; n++) {
    var name = names[n];
    var rule = rules[name];
    if (!Object.prototype.hasOwnProperty.call(message, name)) {
      if (rule.optional === true) continue;
      return { ok: false, reason: "missing_key:" + name };
    }
    if (!valueOk(rule, message[name])) {
      return { ok: false, reason: "bad_value:" + name };
    }
  }
  return { ok: true, type: type };
}
