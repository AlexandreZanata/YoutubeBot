//! Clock, periods and date formatting in the channels' time zone (America/Cuiaba).
//!
//! The bot writes naive local timestamps (`2026-11-17T12:22:17`) and slots
//! (`2026-11-20 12:00`) in America/Cuiaba. Every comparison here uses that zone.

use chrono::{DateTime, Datelike, Duration, NaiveDate, NaiveDateTime, NaiveTime, Utc, Weekday};
use chrono_tz::America::Cuiaba;

pub const TIMEZONE: &str = "America/Cuiaba";

/// Current wall-clock time in America/Cuiaba, independent of the machine's zone.
pub fn now() -> NaiveDateTime {
    Utc::now().with_timezone(&Cuiaba).naive_local()
}

/// Parses an upload slot such as `2026-11-20 12:00` (seconds are accepted).
pub fn parse_slot(value: &str) -> Option<NaiveDateTime> {
    let value = value.trim();
    [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ]
    .iter()
    .find_map(|format| NaiveDateTime::parse_from_str(value, format).ok())
}

/// Parses a record timestamp. Naive values are local to America/Cuiaba; values with an
/// offset (`Z`, `-04:00`) are converted to it. A bare date means its first minute.
pub fn parse_timestamp(value: &str) -> Option<NaiveDateTime> {
    let value = value.trim();
    if value.is_empty() {
        return None;
    }
    if let Ok(moment) = DateTime::parse_from_rfc3339(value) {
        return Some(moment.with_timezone(&Cuiaba).naive_local());
    }
    if let Some(moment) = [
        "%Y-%m-%dT%H:%M:%S%.f",
        "%Y-%m-%d %H:%M:%S%.f",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
    ]
    .iter()
    .find_map(|format| NaiveDateTime::parse_from_str(value, format).ok())
    {
        return Some(moment);
    }
    NaiveDate::parse_from_str(value, "%Y-%m-%d")
        .ok()
        .map(|date| date.and_time(NaiveTime::MIN))
}

/// Accepts the date typed by the owner: `17/11/2026` or `2026-11-17`.
pub fn parse_date_input(value: &str) -> Option<NaiveDate> {
    let value = value.trim();
    NaiveDate::parse_from_str(value, "%d/%m/%Y")
        .or_else(|_| NaiveDate::parse_from_str(value, "%Y-%m-%d"))
        .ok()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PeriodKind {
    ThisMonth,
    Last30Days,
    Custom,
}

/// An inclusive range of calendar days in America/Cuiaba.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Period {
    pub kind: PeriodKind,
    pub start: NaiveDate,
    pub end: NaiveDate,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PeriodError {
    InvalidStart,
    InvalidEnd,
    EndBeforeStart,
}

impl std::fmt::Display for PeriodError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::InvalidStart => "data inicial inválida (use DD/MM/AAAA)",
            Self::InvalidEnd => "data final inválida (use DD/MM/AAAA)",
            Self::EndBeforeStart => "a data final é anterior à inicial",
        })
    }
}

impl std::error::Error for PeriodError {}

impl Period {
    /// The whole calendar month of `today`, including days still ahead.
    pub fn this_month(today: NaiveDate) -> Self {
        let start = today.with_day(1).unwrap_or(today);
        let next = if start.month() == 12 {
            NaiveDate::from_ymd_opt(start.year() + 1, 1, 1)
        } else {
            NaiveDate::from_ymd_opt(start.year(), start.month() + 1, 1)
        };
        let end = next.map(|day| day - Duration::days(1)).unwrap_or(today);
        Self {
            kind: PeriodKind::ThisMonth,
            start,
            end,
        }
    }

    /// Today and the 29 days before it.
    pub fn last_30_days(today: NaiveDate) -> Self {
        Self {
            kind: PeriodKind::Last30Days,
            start: today - Duration::days(29),
            end: today,
        }
    }

    pub fn custom(start: NaiveDate, end: NaiveDate) -> Result<Self, PeriodError> {
        if end < start {
            return Err(PeriodError::EndBeforeStart);
        }
        Ok(Self {
            kind: PeriodKind::Custom,
            start,
            end,
        })
    }

    /// Builds a custom period from the text typed in the two date fields.
    pub fn from_inputs(start: &str, end: &str) -> Result<Self, PeriodError> {
        let start = parse_date_input(start).ok_or(PeriodError::InvalidStart)?;
        let end = parse_date_input(end).ok_or(PeriodError::InvalidEnd)?;
        Self::custom(start, end)
    }

    pub fn contains(&self, moment: NaiveDateTime) -> bool {
        let day = moment.date();
        day >= self.start && day <= self.end
    }

    pub fn contains_opt(&self, moment: Option<NaiveDateTime>) -> bool {
        moment.is_some_and(|value| self.contains(value))
    }

    /// Human label in Brazilian Portuguese.
    pub fn label(&self) -> String {
        match self.kind {
            PeriodKind::ThisMonth => {
                format!(
                    "{} de {}",
                    month_name(self.start.month()),
                    self.start.year()
                )
            }
            PeriodKind::Last30Days => format!(
                "últimos 30 dias ({} a {})",
                format_day_month(self.start),
                format_day_month(self.end)
            ),
            PeriodKind::Custom => {
                format!("{} a {}", format_date(self.start), format_date(self.end))
            }
        }
    }
}

pub fn month_name(month: u32) -> &'static str {
    const NAMES: [&str; 12] = [
        "janeiro",
        "fevereiro",
        "março",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    ];
    NAMES
        .get(month.saturating_sub(1) as usize)
        .copied()
        .unwrap_or("")
}

pub fn weekday_short(day: Weekday) -> &'static str {
    match day {
        Weekday::Mon => "seg",
        Weekday::Tue => "ter",
        Weekday::Wed => "qua",
        Weekday::Thu => "qui",
        Weekday::Fri => "sex",
        Weekday::Sat => "sáb",
        Weekday::Sun => "dom",
    }
}

/// `17/11/2026`
pub fn format_date(day: NaiveDate) -> String {
    day.format("%d/%m/%Y").to_string()
}

/// `17/11`
pub fn format_day_month(day: NaiveDate) -> String {
    day.format("%d/%m").to_string()
}

/// `17/11/2026 12:00`
pub fn format_datetime(moment: NaiveDateTime) -> String {
    moment.format("%d/%m/%Y %H:%M").to_string()
}

/// `ter 17/11 12:00`, used for slots.
pub fn format_slot(moment: NaiveDateTime) -> String {
    format!(
        "{} {}",
        weekday_short(moment.weekday()),
        moment.format("%d/%m %H:%M")
    )
}

/// Relative label for the next slot: `hoje 18:00`, `amanhã 00:00` or `sex 20/11 12:00`.
pub fn format_relative(moment: NaiveDateTime, now: NaiveDateTime) -> String {
    let days = (moment.date() - now.date()).num_days();
    match days {
        0 => format!("hoje {}", moment.format("%H:%M")),
        1 => format!("amanhã {}", moment.format("%H:%M")),
        -1 => format!("ontem {}", moment.format("%H:%M")),
        _ => format_slot(moment),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn day(year: i32, month: u32, value: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(year, month, value).unwrap()
    }

    #[test]
    fn this_month_covers_every_day_of_december() {
        let period = Period::this_month(day(2026, 12, 9));
        assert_eq!(period.start, day(2026, 12, 1));
        assert_eq!(period.end, day(2026, 12, 31));
        assert_eq!(period.label(), "dezembro de 2026");
    }

    #[test]
    fn last_30_days_includes_today() {
        let period = Period::last_30_days(day(2026, 11, 17));
        assert_eq!(period.start, day(2026, 10, 19));
        assert!(period.contains(day(2026, 11, 17).and_hms_opt(23, 59, 0).unwrap()));
        assert!(!period.contains(day(2026, 10, 18).and_hms_opt(23, 59, 0).unwrap()));
    }

    #[test]
    fn custom_period_rejects_inverted_or_invalid_dates() {
        assert_eq!(
            Period::from_inputs("17/11/2026", "01/11/2026"),
            Err(PeriodError::EndBeforeStart)
        );
        assert_eq!(
            Period::from_inputs("31/02/2026", "01/03/2026"),
            Err(PeriodError::InvalidStart)
        );
        let period = Period::from_inputs("2026-11-01", "15/11/2026").unwrap();
        assert_eq!(period.label(), "01/11/2026 a 15/11/2026");
    }

    #[test]
    fn timestamps_with_offsets_are_converted_to_cuiaba() {
        let utc = parse_timestamp("2026-11-17T16:00:00Z").unwrap();
        assert_eq!(utc, day(2026, 11, 17).and_hms_opt(12, 0, 0).unwrap());
        let naive = parse_timestamp("2026-11-17T12:22:17").unwrap();
        assert_eq!(naive, day(2026, 11, 17).and_hms_opt(12, 22, 17).unwrap());
        assert_eq!(
            parse_timestamp("2026-11-17T12:22:17.512").unwrap().date(),
            day(2026, 11, 17)
        );
        assert!(parse_timestamp("11:58 AM").is_none());
    }

    #[test]
    fn slots_and_labels_are_formatted_in_portuguese() {
        let slot = parse_slot("2026-11-20 12:00").unwrap();
        assert_eq!(format_slot(slot), "sex 20/11 12:00");
        let now = parse_slot("2026-11-19 08:00").unwrap();
        assert_eq!(format_relative(slot, now), "amanhã 12:00");
        assert_eq!(format_relative(slot, slot), "hoje 12:00");
    }
}
