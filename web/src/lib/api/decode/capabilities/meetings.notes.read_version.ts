import type { Decoder } from "../types";
import { strictObject, nullable, checked, text, integer, boolean, enumeration, identifier, digest, timestamp, type Decoded } from "./continuity.projects.create";

/*
 * `meetings.notes.read_version` (record lineage S1 contract section 7.2): one
 * exact note version of one Meeting. `body_markdown` is present only when the
 * request asked for it, so the note has two closed shapes; any other key is
 * refused. The Python model is `MeetingNoteVersionView` in
 * `contracts/v1/meetings.py`.
 */
const MAX_MEETING_NOTES_CHARACTERS = 100000;

const noteCore = {
  note_version_id: identifier("mnote"),
  meeting_id: identifier("mtg"),
  version_number: integer(1),
  supersedes_note_version_id: nullable(identifier("mnote")),
  content_sha256: digest,
  character_count: integer(1, MAX_MEETING_NOTES_CHARACTERS),
  recorded_at: timestamp,
  is_current: boolean,
};
const withoutBody = strictObject(noteCore);
const withBody = checked(
  strictObject({ ...noteCore, body_markdown: text(1, MAX_MEETING_NOTES_CHARACTERS) }),
  (value) => Array.from(value.body_markdown).length === value.character_count,
);

export type MeetingNoteVersion = Decoded<typeof withoutBody> & { readonly body_markdown?: string };
const note: Decoder<MeetingNoteVersion> = (input) =>
  input !== null && typeof input === "object" && Object.hasOwn(input, "body_markdown")
    ? withBody(input)
    : withoutBody(input);

const readVersion = strictObject({ note, evidence_availability: enumeration(["available"]) });
export type MeetingsNotesReadVersionResult = Decoded<typeof readVersion>;
export const decodeMeetingsNotesReadVersion: Decoder<MeetingsNotesReadVersionResult> = readVersion;
