//! Accent- and case-insensitive search used by the Ctrl+K field.

/// Lowercases and strips the Portuguese diacritics so "acao" finds "Ação".
pub fn normalize(text: &str) -> String {
    text.chars()
        .flat_map(char::to_lowercase)
        .map(|character| match character {
            'á' | 'à' | 'â' | 'ã' | 'ä' => 'a',
            'é' | 'è' | 'ê' | 'ë' => 'e',
            'í' | 'ì' | 'î' | 'ï' => 'i',
            'ó' | 'ò' | 'ô' | 'õ' | 'ö' => 'o',
            'ú' | 'ù' | 'û' | 'ü' => 'u',
            'ç' => 'c',
            'ñ' => 'n',
            other => other,
        })
        .collect()
}

/// True when every whitespace-separated term of `query` appears in at least one field.
/// An empty query matches everything.
pub fn matches(query: &str, fields: &[&str]) -> bool {
    let haystack: Vec<String> = fields.iter().map(|field| normalize(field)).collect();
    normalize(query)
        .split_whitespace()
        .all(|term| haystack.iter().any(|field| field.contains(term)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn search_ignores_case_and_accents_and_needs_every_term() {
        assert!(matches(
            "adubacao sulco",
            &["Adubação Fosfatada", "no Sulco"]
        ));
        assert!(matches("", &["anything"]));
        assert!(!matches("adubacao milho", &["Adubação Fosfatada"]));
    }
}
