import EventKit

/// Compile-only evidence for the public Reminders read shapes. No store is
/// opened, no permission is requested, and no personal data is accessed.
public enum TasksEventKitShape {
    public static let reminderType: EKReminder.Type = EKReminder.self
    public static let calendarType: EKCalendar.Type = EKCalendar.self
    public static let reminderIdentifier = \EKReminder.calendarItemIdentifier
    public static let listIdentifier = \EKCalendar.calendarIdentifier
}
