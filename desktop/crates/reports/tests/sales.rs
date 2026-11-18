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

mod fichas {
    use std::fs;
    use std::path::{Path, PathBuf};

    use reports::sales::{CENTRAL_PATH, CLIENTS_DIR, MediaKind, load_sales};
    use serde_json::{Value, json};

    fn write_central(root: &Path, fichas: Value) {
        let path = root.join(CENTRAL_PATH);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        let central = json!({"generated_at": "2026-11-18T10:00:00-04:00", "fichas": fichas});
        fs::write(path, central.to_string()).unwrap();
    }

    /// `clientes/<name>/` with a ficha.md and the given files under `midia/`.
    fn client(root: &Path, name: &str, files: &[&str]) -> PathBuf {
        let folder = root.join(CLIENTS_DIR).join(name);
        fs::create_dir_all(folder.join("midia")).unwrap();
        fs::write(folder.join("ficha.md"), "# Ficha").unwrap();
        for file in files {
            fs::write(folder.join("midia").join(file), b"demo").unwrap();
        }
        folder
    }

    fn text(path: &Path) -> String {
        path.to_string_lossy().into_owned()
    }

    #[test]
    fn a_central_without_fichas_has_none() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join(CENTRAL_PATH);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(
            &path,
            r#"{"generated_at": "2026-11-18T10:00:00-04:00", "leads": [{}]}"#,
        )
        .unwrap();
        let report = load_sales(temp.path());
        assert!(report.available());
        assert!(report.fichas.is_empty());
        assert_eq!(report.source.skipped, 0);
    }

    #[test]
    fn fichas_are_read_newest_first_with_defaults() {
        let temp = tempfile::tempdir().unwrap();
        let site = client(temp.path(), "barbearia-2-L1", &["logo.jpg", "voz.ogg"]);
        let sistema = client(temp.path(), "oficina-1-L2", &[]);
        write_central(
            temp.path(),
            json!([
                {"lead": "L2", "folder": text(&sistema), "updated_at": "2026-11-17T08:00:00-04:00"},
                {
                    "lead": "L1", "label": "barbearia-2", "name": "Barbearia Teste",
                    "state": "qualifying", "state_label": "Coletando dados", "kind": "Site",
                    "status": "coletando dados", "updated_at": "2026-11-18T09:40:00-04:00",
                    "resumo": "Quer um site com agenda.",
                    "sections": [
                        {"title": "Empresa", "items": [
                            {"label": "Nome", "value": "Barbearia Teste"},
                            {"label": "", "value": ""}
                        ]},
                        {"title": "Vazia", "items": []},
                        "not a section"
                    ],
                    "pendencias": ["cores da marca", "", 42, null],
                    "duvidas": "not a list",
                    "media": [
                        {"kind": "image", "path": text(&site.join("midia/logo.jpg")),
                         "caption": "logo", "at": "2026-11-18T09:00:00-04:00"},
                        {"kind": "sticker", "path": text(&site.join("midia/voz.ogg")), "name": "Voz"}
                    ],
                    "ficha_md": text(&site.join("ficha.md")), "folder": text(&site),
                    "phone": "+55 65 90000-0001", "wa_link": "https://wa.me/556590000001"
                }
            ]),
        );
        let report = load_sales(temp.path());
        assert_eq!(report.source.skipped, 0);
        assert_eq!(
            report
                .fichas
                .iter()
                .map(|ficha| ficha.lead.as_str())
                .collect::<Vec<_>>(),
            ["L1", "L2"]
        );

        let ficha = report.ficha("L1").unwrap();
        assert_eq!(ficha.kind, "site");
        assert_eq!(ficha.sections.len(), 1);
        assert_eq!(ficha.sections[0].items.len(), 1);
        assert_eq!(ficha.pendencias, ["cores da marca", "42"]);
        assert!(ficha.duvidas.is_empty());
        assert_eq!(ficha.media.len(), 2);
        assert_eq!(ficha.media[0].kind, MediaKind::Image);
        assert_eq!(ficha.media[0].name, "logo.jpg");
        assert_eq!(
            ficha.media[0].at.unwrap().format("%H:%M").to_string(),
            "09:00"
        );
        assert_eq!(ficha.media[1].kind, MediaKind::Document);
        assert_eq!(ficha.media[1].name, "Voz");
        assert_eq!(ficha.wa_link, "https://wa.me/556590000001");
        assert!(ficha.open_markdown(temp.path()).is_some());
        assert!(ficha.open_folder(temp.path()).is_some());
        assert!(ficha.open_media(temp.path(), 0).is_some());

        let bare = report.ficha("L2").unwrap();
        assert!(bare.name.is_empty() && bare.kind.is_empty() && bare.resumo.is_empty());
        assert!(bare.sections.is_empty() && bare.media.is_empty() && bare.pendencias.is_empty());
        assert!(bare.ficha_md.is_none() && bare.updated_at.is_some());
        assert!(bare.open_markdown(temp.path()).is_none());
    }

    #[test]
    fn paths_outside_the_clients_folder_are_dropped() {
        let temp = tempfile::tempdir().unwrap();
        let good = client(temp.path(), "padaria-1-L1", &["foto.png"]);
        let other = client(temp.path(), "salao-1-L9", &["alheia.png"]);
        let clients = temp.path().join(CLIENTS_DIR);
        let outside = temp.path().join("outside");
        fs::create_dir_all(&outside).unwrap();
        fs::write(outside.join("ficha.md"), "x").unwrap();
        fs::write(outside.join("foto.png"), "x").unwrap();
        let escape = format!("{}/../../../../../outside", good.display());
        write_central(
            temp.path(),
            json!([
                {"lead": "L1", "folder": text(&good), "media": [
                    {"kind": "image", "path": text(&good.join("midia/foto.png"))},
                    {"kind": "image", "path": text(&other.join("midia/alheia.png"))},
                    {"kind": "image", "path": text(&outside.join("foto.png"))},
                    {"kind": "image", "path": format!("{}/midia/../../salao-1-L9/midia/alheia.png", good.display())},
                    {"kind": "image", "path": "midia/foto.png"}
                ]},
                {"lead": "L2", "folder": text(&outside)},
                {"lead": "L3", "folder": escape},
                {"lead": "L4", "folder": text(&clients)},
                {"lead": "L5", "folder": "relative/clientes/x"},
                {"lead": "L6", "folder": text(&good), "ficha_md": text(&outside.join("ficha.md"))},
                {"lead": "", "folder": text(&good)},
                "not an object"
            ]),
        );
        let report = load_sales(temp.path());
        assert!(report.available());
        assert_eq!(report.fichas.len(), 1);
        let ficha = &report.fichas[0];
        assert_eq!(ficha.lead, "L1");
        assert_eq!(ficha.media.len(), 1);
        assert!(ficha.media[0].path.ends_with("padaria-1-L1/midia/foto.png"));
        // 7 fichas and 4 media items were refused.
        assert_eq!(report.source.skipped, 11);
    }

    #[test]
    fn a_ficha_folder_that_does_not_exist_yet_is_checked_lexically() {
        let temp = tempfile::tempdir().unwrap();
        fs::create_dir_all(temp.path().join(CLIENTS_DIR)).unwrap();
        let future = temp.path().join(CLIENTS_DIR).join("nova-L7");
        write_central(
            temp.path(),
            json!([
                {"lead": "L7", "folder": text(&future), "media": [
                    {"kind": "audio", "path": text(&future.join("midia/a.ogg"))}
                ]},
                {"lead": "L8", "folder": format!("{}/./x/../../fora", future.display())}
            ]),
        );
        let report = load_sales(temp.path());
        assert_eq!(report.fichas.len(), 1);
        assert_eq!(report.fichas[0].media.len(), 1);
        assert!(report.fichas[0].open_folder(temp.path()).is_none());
        assert!(report.fichas[0].open_media(temp.path(), 0).is_none());
    }

    #[test]
    fn fichas_that_are_not_a_list_leave_the_page_readable() {
        let temp = tempfile::tempdir().unwrap();
        write_central(temp.path(), json!({"L1": {}}));
        let report = load_sales(temp.path());
        assert!(report.available());
        assert!(report.fichas.is_empty());
    }

    #[test]
    fn only_known_media_types_inside_the_folder_can_be_opened() {
        let temp = tempfile::tempdir().unwrap();
        let folder = client(
            temp.path(),
            "loja-1-L1",
            &["nota.pdf", "abrir.desktop", "run.sh"],
        );
        let media = |name: &str| json!({"kind": "document", "path": text(&folder.join("midia").join(name))});
        write_central(
            temp.path(),
            json!([{"lead": "L1", "folder": text(&folder), "media": [
                media("nota.pdf"), media("abrir.desktop"), media("run.sh"), media("sumiu.pdf")
            ]}]),
        );
        let report = load_sales(temp.path());
        let ficha = &report.fichas[0];
        assert_eq!(ficha.media.len(), 4);
        assert!(ficha.open_media(temp.path(), 0).is_some());
        assert!(ficha.open_media(temp.path(), 1).is_none());
        assert!(ficha.open_media(temp.path(), 2).is_none());
        assert!(ficha.open_media(temp.path(), 3).is_none());
        assert!(ficha.open_media(temp.path(), 9).is_none());
    }

    #[cfg(unix)]
    #[test]
    fn a_symlink_cannot_lead_a_ficha_or_its_media_outside() {
        let temp = tempfile::tempdir().unwrap();
        let folder = client(temp.path(), "loja-2-L1", &[]);
        let outside = temp.path().join("outside");
        fs::create_dir_all(&outside).unwrap();
        fs::write(outside.join("segredo.png"), "x").unwrap();
        std::os::unix::fs::symlink(outside.join("segredo.png"), folder.join("midia/link.png"))
            .unwrap();
        let linked = temp.path().join(CLIENTS_DIR).join("link-L2");
        std::os::unix::fs::symlink(&outside, &linked).unwrap();
        write_central(
            temp.path(),
            json!([
                {"lead": "L1", "folder": text(&folder), "media": [
                    {"kind": "image", "path": text(&folder.join("midia/link.png"))}
                ]},
                {"lead": "L2", "folder": text(&linked)}
            ]),
        );
        let report = load_sales(temp.path());
        assert_eq!(report.fichas.len(), 1);
        assert!(report.fichas[0].media.is_empty());
        assert_eq!(report.source.skipped, 2);
    }
}
