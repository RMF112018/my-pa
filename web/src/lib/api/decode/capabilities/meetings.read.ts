import type { Decoder } from "../types";
import { strictObject, nullable, arrayOf, checked, text, integer, boolean, enumeration, identifier, timestamp, type Decoded } from "./continuity.projects.create";

export const mediaType = enumeration(["application/json", "application/octet-stream", "application/pdf", "text/markdown", "text/plain"]);
const nonblank = (max: number) => checked(text(1,max), (value) => /[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u.test(value));
export const meetingTitle = nonblank(200);
// Keep this small boundary local: importing work-route would create a cycle
// through gateway -> registry -> decoder. Host ZoneInfo owns availability.
const timezone = checked(text(1,64), (value) => {
  const pythonOuterSpace = /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu;
  if (value !== value.replace(pythonOuterSpace, "") ||
    /\u0000|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value) ||
    value.startsWith("/") || value.includes("\\")) return false;
  return value.split("/").every((segment) => segment !== "" && segment !== "." && segment !== "..");
});
// Canonical Python urlsplit accepts raw Unicode hosts, IPvFuture and scoped
// IPv6. Keep these pure checks local to avoid a decoder -> route import cycle;
// validation must preserve the original URL rather than WHATWG-normalize it.
/** IPv6 bracket syntax used by canonical urllib.parse, including a nonempty scope. */
function meetingIpv6Host(host: string): boolean {
  const scoped = host.split("%");
  if (scoped.length > 2 || (scoped.length === 2 && !scoped[1])) return false;
  let address = scoped[0]!;
  if (address.includes(".")) {
    const colon = address.lastIndexOf(":");
    if (colon < 0) return false;
    const octets = address.slice(colon + 1).split(".");
    if (octets.length !== 4 || octets.some((octet) => !/^(0|[1-9][0-9]{0,2})$/.test(octet) || Number(octet) > 255)) return false;
    address = `${address.slice(0, colon + 1)}0:0`;
  }
  const halves = address.split("::");
  if (halves.length > 2) return false;
  const groups = halves.flatMap((half) => half === "" ? [] : half.split(":"));
  if (groups.some((group) => !/^[0-9a-fA-F]{1,4}$/.test(group))) return false;
  return halves.length === 2 ? groups.length < 8 : groups.length === 8;
}

const httpsUrl = checked(text(1,2048), (value) => {
  const pythonOuterSpace = /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu;
  if (value !== value.replace(pythonOuterSpace, "") || /[\u0000-\u0020\u007F]/u.test(value)) return false;
  if (value.slice(0, 8).toLowerCase() !== "https://") return false;
  const netloc = value.slice(8).split(/[/?#]/, 1)[0]!;
  // Presence, even empty userinfo, is refused by parsed.username/password.
  if (!netloc || netloc.includes("@")) return false;
  const normalized = netloc.replace(/[@:#?]/g, "").normalize("NFKC");
  if (/[/?#@:]/.test(normalized)) return false;
  let hostname: string, port: string;
  if (netloc.includes("[") || netloc.includes("]")) {
    if (!netloc.startsWith("[") || !netloc.includes("]")) return false;
    const end = netloc.indexOf("]");
    hostname = netloc.slice(1, end);
    const tail = netloc.slice(end + 1);
    if (tail && !tail.startsWith(":")) return false;
    port = tail ? tail.slice(1) : "";
    if (hostname.startsWith("v")) {
      if (!/^v[0-9a-fA-F]+\..+$/.test(hostname)) return false;
    } else if (!meetingIpv6Host(hostname)) return false;
  } else {
    const colon = netloc.indexOf(":");
    hostname = colon < 0 ? netloc : netloc.slice(0, colon);
    port = colon < 0 ? "" : netloc.slice(colon + 1);
  }
  return !!hostname && (port === "" || (/^[0-9]+$/.test(port) && Number(port) <= 65535));
});
const attendee = checked(strictObject({
  attendee_id: identifier("matt"), entity_id: nullable(identifier("ent")), display_name: nullable(text(1,200)), email: nullable(text(1,320)),
  is_organizer: boolean, response_status: enumeration(["unknown", "needs_action", "accepted", "declined", "tentative"]), added_at: timestamp,
}), (value) => value.entity_id !== null || value.display_name !== null || value.email !== null);
const attachment = checked(strictObject({
  attachment_id: identifier("matc"), document_id: identifier("mdoc"), availability: enumeration(["active", "archived", "unavailable"]),
  title: nullable(text(1,200)), media_type: nullable(mediaType), added_at: timestamp,
}), (value) => value.availability === "unavailable" || (value.title !== null && value.media_type !== null));
const note = strictObject({note_version_id: identifier("mnote"), version_number: integer(1), body_markdown: nonblank(100000), recorded_at: timestamp});
export const meetingCore = {
  meeting_id: identifier("mtg"), meeting_series_id: nullable(identifier("mser")), series_title: nullable(meetingTitle), series_version: nullable(integer(1)),
  title: meetingTitle, status: enumeration(["scheduled", "cancelled"]), start_at: timestamp, end_at: nullable(timestamp), timezone_name: timezone,
  location_text: nullable(text(0,500)), project_id: nullable(identifier("prj")), version: integer(1), updated_at: timestamp,
};
type Core = Decoded<ReturnType<typeof strictObject<typeof meetingCore>>>;
// Canonical Python datetimes retain microseconds; Date.parse truncates them.
function timestampMicros(value: string): bigint {
  const fraction = /\.(\d+)(?=Z|[+-]\d{2}:\d{2}$)/.exec(value)?.[1] ?? "";
  const seconds = value.replace(/\.\d+(?=Z|[+-]\d{2}:\d{2}$)/, "");
  return BigInt(Date.parse(seconds)) * BigInt(1000) + BigInt(fraction.padEnd(6, "0").slice(0, 6));
}
export function validMeetingCore(value: Core): boolean {
  return (value.meeting_series_id === null) === (value.series_title === null) &&
    (value.meeting_series_id !== null || value.series_version === null) &&
    (value.end_at === null || timestampMicros(value.end_at) >= timestampMicros(value.start_at));
}
export const meetingView = checked(strictObject({
  ...meetingCore, virtual_meeting_url: nullable(httpsUrl), description: nullable(text(0,100000)),
  created_at: timestamp, cancelled_at: nullable(timestamp), attendees: arrayOf(attendee,100), attachments: arrayOf(attachment,50), notes: nullable(note),
}), (value) => validMeetingCore(value) && (value.status === "cancelled") === (value.cancelled_at !== null) &&
  new Set(value.attendees.map((row) => row.attendee_id)).size === value.attendees.length &&
  value.attendees.filter((row) => row.is_organizer).length <= 1 &&
  new Set(value.attachments.map((row) => row.attachment_id)).size === value.attachments.length &&
  new Set(value.attachments.map((row) => row.document_id)).size === value.attachments.length);
const read = strictObject({meeting: meetingView});
export type MeetingsReadResult = Decoded<typeof read>;
export const decodeMeetingsRead: Decoder<MeetingsReadResult> = read;
