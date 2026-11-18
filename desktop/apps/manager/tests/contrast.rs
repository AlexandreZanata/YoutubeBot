//! WCAG AA contrast of the design tokens in `ui/theme.slint`, for both themes: 4.5:1 for text
//! on every surface it is drawn on, 3:1 for focus rings, control outlines and filled buttons.

use std::collections::HashMap;

const THEME: &str = include_str!("../ui/theme.slint");

/// `name -> (dark, light)` from lines like `out property <color> bg: dark ? #0e0e10 : #f4f4f5;`.
fn tokens() -> HashMap<String, (String, String)> {
    THEME
        .lines()
        .filter_map(|line| {
            let rest = line.trim().strip_prefix("out property <color> ")?;
            let (name, value) = rest.split_once(": dark ? ")?;
            let (dark, light) = value.trim_end_matches(';').split_once(" : ")?;
            Some((name.to_owned(), (dark.to_owned(), light.to_owned())))
        })
        .collect()
}

fn luminance(hex: &str) -> f64 {
    let channel = |index: usize| {
        let value =
            u8::from_str_radix(&hex[1 + index * 2..3 + index * 2], 16).unwrap() as f64 / 255.0;
        if value <= 0.03928 {
            value / 12.92
        } else {
            ((value + 0.055) / 1.055).powf(2.4)
        }
    };
    0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2)
}

fn ratio(first: &str, second: &str) -> f64 {
    let (a, b) = (luminance(first), luminance(second));
    (a.max(b) + 0.05) / (a.min(b) + 0.05)
}

fn check(pairs: &[(&str, &str)], minimum: f64) -> Vec<String> {
    let tokens = tokens();
    let mut failures = Vec::new();
    for (foreground, background) in pairs {
        let (fg_dark, fg_light) = &tokens[*foreground];
        let (bg_dark, bg_light) = &tokens[*background];
        for (theme, fg, bg) in [("dark", fg_dark, bg_dark), ("light", fg_light, bg_light)] {
            let value = ratio(fg, bg);
            if value < minimum {
                failures.push(format!(
                    "{theme}: {foreground} on {background} = {value:.2}"
                ));
            }
        }
    }
    failures
}

const SURFACES: [&str; 6] = [
    "bg",
    "sidebar",
    "surface",
    "surface-alt",
    "hover",
    "selected",
];

#[test]
fn the_parser_sees_every_color_token() {
    assert!(
        tokens().len() >= 20,
        "theme.slint color lines changed format"
    );
}

#[test]
fn text_tokens_reach_aa_on_every_surface() {
    let texts = [
        "text",
        "text-muted",
        "text-subtle",
        "accent",
        "success",
        "warning",
        "danger",
    ];
    let pairs: Vec<(&str, &str)> = texts
        .iter()
        .flat_map(|text| SURFACES.iter().map(move |surface| (*text, *surface)))
        .chain([("on-primary", "primary")])
        .collect();
    let failures = check(&pairs, 4.5);
    assert!(failures.is_empty(), "{failures:#?}");
}

#[test]
fn focus_rings_and_control_outlines_reach_three_to_one() {
    let pairs: Vec<(&str, &str)> = ["focus", "border-strong", "primary"]
        .iter()
        .flat_map(|token| {
            ["bg", "sidebar", "surface"]
                .iter()
                .map(move |surface| (*token, *surface))
        })
        .collect();
    let failures = check(&pairs, 3.0);
    assert!(failures.is_empty(), "{failures:#?}");
}
