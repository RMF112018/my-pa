import type { Decoder } from "../types";
import { strictObject, arrayOf, checked, integer, type Decoded } from "./continuity.projects.create";
import { meetingCore, validMeetingCore } from "./meetings.read";
const row = checked(strictObject({...meetingCore, attendee_count: integer(0,100), attachment_count: integer(0,50)}), validMeetingCore);
export const meetingPage = strictObject({meetings: arrayOf(row)});
export type MeetingsListResult = Decoded<typeof meetingPage>;
export const decodeMeetingsList: Decoder<MeetingsListResult> = meetingPage;
