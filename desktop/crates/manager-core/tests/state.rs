use std::fs;

use manager_core::{SessionInfo, StateLoader};

fn registry() -> String {
    r#"{
      "schema": 1,
      "accounts": {
        "zaflas": {"id": "zaflas", "label": "Zaflas", "cdp_port": 9302, "browser_mode": "system"}
      },
      "bindings": {
        "zaflas": {"account_id": "zaflas", "channel_id": "UCi2aftoK7vlS3A6OozMHXKg"}
      }
    }"#
    .to_owned()
}

#[test]
fn loads_youtube_channels_and_network_sessions() {
    let temp = tempfile::tempdir().expect("temp dir");
    let root = temp.path();
    fs::create_dir_all(root.join(".local/accounts")).unwrap();
    fs::write(root.join(".local/accounts/registry.json"), registry()).unwrap();
    fs::create_dir_all(root.join(".local/commercial/whatsapp")).unwrap();
    fs::write(
        root.join(".local/commercial/whatsapp/account.json"),
        r#"{"state":"logged-in","handle":"whatsapp","display_name":"WhatsApp Web","verified_at":"2026-11-17T12:22:17"}"#,
    )
    .unwrap();

    let sessions = StateLoader::new(root).load().expect("load");
    let youtube: Vec<&SessionInfo> = sessions.iter().filter(|s| s.scope == "youtube").collect();
    assert_eq!(youtube.len(), 1);
    assert_eq!(youtube[0].label, "Zaflas");
    assert_eq!(youtube[0].channel, "UCi2aftoK7vlS3A6OozMHXKg");
    let whatsapp = sessions
        .iter()
        .find(|s| s.key == "whatsapp")
        .expect("whatsapp");
    assert_eq!(whatsapp.status, "logged-in");
    assert!(whatsapp.supports_actions());
    assert!(!whatsapp.running, "no browser.pid means no live browser");
}

#[test]
fn a_dead_or_live_browser_pid_is_reported_without_signals() {
    let temp = tempfile::tempdir().expect("temp dir");
    let root = temp.path();
    let x = root.join(".local/social/x");
    fs::create_dir_all(&x).unwrap();
    fs::write(x.join("account.json"), r#"{"state":"logged-in"}"#).unwrap();
    let own = std::process::id();
    fs::write(
        x.join("browser.pid"),
        format!(r#"{{"pid":{own},"port":9322,"mode":"hidden"}}"#),
    )
    .unwrap();
    let whatsapp = root.join(".local/commercial/whatsapp");
    fs::create_dir_all(&whatsapp).unwrap();
    fs::write(
        whatsapp.join("browser.pid"),
        r#"{"pid":4294967294,"mode":"visible"}"#,
    )
    .unwrap();

    let sessions = StateLoader::new(root).load().expect("load");
    let x = sessions.iter().find(|s| s.key == "x").unwrap();
    assert!(x.running);
    assert_eq!(x.mode, "hidden");
    let whatsapp = sessions.iter().find(|s| s.key == "whatsapp").unwrap();
    assert!(!whatsapp.running);
    assert_eq!(whatsapp.status, "não conectado");
}

#[test]
fn missing_registry_yields_network_placeholders_only() {
    let temp = tempfile::tempdir().expect("temp dir");
    let sessions = StateLoader::new(temp.path()).load().expect("load");
    assert!(sessions.iter().all(|s| s.scope != "youtube"));
    assert_eq!(sessions.len(), 4);
    assert!(sessions.iter().all(|s| s.status == "não conectado"));
}
