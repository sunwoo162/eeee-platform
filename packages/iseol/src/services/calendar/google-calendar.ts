import { google, calendar_v3 } from "googleapis";

export type CalendarEventInput = {
  summary: string;
  description?: string;
  start: string;
  end: string;
  metadata?: Record<string, string>;
};

export type CalendarEventRef = { id: string; htmlLink: string };

export class GoogleCalendarService {
  private readonly calendar: calendar_v3.Calendar;

  constructor(clientId: string, clientSecret: string, refreshToken: string, redirectUri: string) {
    if (!clientId || !clientSecret || !refreshToken) throw new Error("Google Calendar OAuth 설정이 필요합니다.");
    const auth = new google.auth.OAuth2(clientId, clientSecret, redirectUri || undefined);
    auth.setCredentials({ refresh_token: refreshToken });
    this.calendar = google.calendar({ version: "v3", auth });
  }

  async createProjectCalendar(name: string): Promise<{ id: string; url: string }> {
    const { data } = await this.calendar.calendars.insert({ requestBody: { summary: `이설 · ${name}`, timeZone: "Asia/Seoul" } });
    if (!data.id) throw new Error("Google Calendar 생성 결과에 calendar id가 없습니다.");
    return { id: data.id, url: `https://calendar.google.com/calendar/u/0/r?cid=${encodeURIComponent(data.id)}` };
  }

  async deleteProjectCalendar(calendarId: string): Promise<void> {
    await this.calendar.calendars.delete({ calendarId });
  }

  async createEvent(calendarId: string, input: CalendarEventInput): Promise<CalendarEventRef> {
    const { data } = await this.calendar.events.insert({
      calendarId,
      requestBody: this.eventBody(input),
    });
    if (!data.id) throw new Error("Google Calendar 일정 생성 결과에 event id가 없습니다.");
    return { id: data.id, htmlLink: data.htmlLink ?? "" };
  }

  async updateEvent(calendarId: string, eventId: string, input: CalendarEventInput): Promise<CalendarEventRef> {
    const { data } = await this.calendar.events.patch({ calendarId, eventId, requestBody: this.eventBody(input) });
    if (!data.id) throw new Error("Google Calendar 일정 수정 결과에 event id가 없습니다.");
    return { id: data.id, htmlLink: data.htmlLink ?? "" };
  }

  async deleteEvent(calendarId: string, eventId: string): Promise<void> {
    await this.calendar.events.delete({ calendarId, eventId });
  }

  async listEvents(calendarId: string, timeMin = new Date().toISOString()): Promise<calendar_v3.Schema$Event[]> {
    const { data } = await this.calendar.events.list({ calendarId, timeMin, singleEvents: true, orderBy: "startTime", maxResults: 25 });
    return data.items ?? [];
  }

  private eventBody(input: CalendarEventInput): calendar_v3.Schema$Event {
    return {
      summary: input.summary,
      description: input.description,
      start: { dateTime: input.start, timeZone: "Asia/Seoul" },
      end: { dateTime: input.end, timeZone: "Asia/Seoul" },
      extendedProperties: input.metadata ? { private: input.metadata } : undefined,
    };
  }
}

