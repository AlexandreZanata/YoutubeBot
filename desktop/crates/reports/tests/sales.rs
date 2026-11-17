//! The Central reads the sales agent's central.json leniently and opens only safe targets.

use std::fs;

use reports::sales::{CENTRAL_PATH, load_sales, safe_ficha, safe_wa_link};
use reports::{Snapshot, SourceState};

const CENTRAL: &str = r#"{
  "generated_at": "2026-11-17T16:20:00-04:00",
  "states": [
    {"state": "needs-owner", "label": "Precisa de você", "group": "Com você", "owner": true, "count": 2},
    {"state": "quote-requested", "label": "Orçamento a fazer", "group": "Com você", "owner": true, "count": 1},
    {"state": "engaged", "label": "Em conversa", "group": "Em conversa", "owner": false, "count": "3"},
    {"state": "opened", "label": "Abordado", "group": "Prospecção", "owner": false, "count": null}
  ],
  "interventions": [
    {"lead": "L1", "label": "barbearia-1", "name": "Barbearia Teste", "phone": "+55 65 90000-0001",
     "wa_link": "https://wa.me/5565900000001", "state": "needs-owner", "state_label": "Precisa de você",
     "priority": "hot", "reason": "Quer fechar", "last_message": "Como pago?",
     "at": "2026-11-17T16:10:00-04:00", "ficha": "", "unknown_field": 1},
    {"lead": "", "name": "sem lead, ignorado"}
  ],
  "messages": [
    {"at": "2026-11-17T16:10:00-04:00", "label": "barbearia-1", "name": "Barbearia Teste",
     "dir": "in", "text": "Como pago?", "media": "", "needs_owner": true}
  ],
  "leads": [{}, {}, {}, {}, {}, {}]
}"#;

#[test]
fn central_is_read_with_groups_and_owner_total() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join(CENTRAL_PATH);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(&path, CENTRAL).unwrap();
    let report = load_sales(temp.path());
    assert!(report.available());
    assert_eq!(report.owner_total(), 3);
    assert_eq!(
        report.groups(),
        vec![
            ("Com você".to_owned(), 3),
            ("Em conversa".to_owned(), 3),
            ("Prospecção".to_owned(), 0)
        ]
    );
    assert_eq!(report.interventions.len(), 1);
    assert_eq!(report.interventions[0].label, "barbearia-1");
    assert_eq!(
        report.interventions[0]
            .at
            .unwrap()
            .format("%H:%M")
            .to_string(),
        "16:10"
    );
    assert_eq!(report.messages[0].dir, "in");
    assert_eq!(report.source.records, 6);
    let snapshot = Snapshot::load(temp.path(), report.generated_at.unwrap());
    assert!(
        snapshot
            .sources()
            .iter()
            .any(|source| source.path == CENTRAL_PATH)
    );
}

#[test]
fn missing_and_broken_files_are_reported_not_counted_as_zero() {
    let temp = tempfile::tempdir().unwrap();
    assert_eq!(load_sales(temp.path()).source.state, SourceState::Missing);
    let path = temp.path().join(CENTRAL_PATH);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(&path, "{broken").unwrap();
    assert!(matches!(
        load_sales(temp.path()).source.state,
        SourceState::Invalid(_)
    ));
}

#[test]
fn only_wa_me_numbers_and_client_fichas_can_be_opened() {
    assert!(safe_wa_link("https://wa.me/5565900000001"));
    assert!(!safe_wa_link("https://wa.me/55659000a0001"));
    assert!(!safe_wa_link("https://evil.example/5565900000001"));
    assert!(!safe_wa_link("https://wa.me/123"));

    let temp = tempfile::tempdir().unwrap();
    let folder = temp
        .path()
        .join(".local/commercial/whatsapp/sales/clientes/barbearia-L1");
    fs::create_dir_all(&folder).unwrap();
    fs::write(folder.join("ficha.md"), "# Ficha").unwrap();
    fs::write(temp.path().join("outside.md"), "x").unwrap();
    let ficha = folder.join("ficha.md");
    assert!(safe_ficha(temp.path(), &ficha.to_string_lossy()).is_some());
    assert!(
        safe_ficha(
            temp.path(),
            &temp.path().join("outside.md").to_string_lossy()
        )
        .is_none()
    );
    let escape = folder.join("../../../../../outside.md");
    assert!(safe_ficha(temp.path(), &escape.to_string_lossy()).is_none());
    assert!(safe_ficha(temp.path(), "").is_none());
}
