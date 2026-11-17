//! Maps `reports` results to the display structs of the Slint UI. Formatting only: every count
//! comes from the `reports` crate and every missing source is said as such, never as zero.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use manager_core::SessionInfo;
use reports::commercial::format_price;
use reports::overview::{self, ChannelSummary};
use reports::search::matches;
use reports::snapshot::{Binding, Snapshot};
use reports::social::NetworkAccount;
use reports::time::{self, format_datetime, format_relative, format_slot};
use reports::{NaiveDateTime, Period, SourceState, SourceStatus, VideoKind, VideoState};
use slint::{Image, ModelRc, SharedString, VecModel};

use crate::{
    ChannelCard, ContactRow, Fact, Kpi, Notice, ProductRow, SessionRow, ShortRow, SourceRow,
    UpcomingRow, VideoRow, XPostRow,
};

pub struct Context<'a> {
    pub snapshot: &'a Snapshot,
    pub period: &'a Period,
    pub now: NaiveDateTime,
    pub search: &'a str,
    pub channel: Option<&'a str>,
}

pub fn model<T: Clone + 'static>(rows: Vec<T>) -> ModelRc<T> {
    ModelRc::new(VecModel::from(rows))
}

fn text(value: impl AsRef<str>) -> SharedString {
    SharedString::from(value.as_ref())
}

pub fn notice(kind: i32, title: &str, message: impl AsRef<str>) -> Notice {
    Notice {
        kind,
        title: text(title),
        message: text(message),
    }
}

pub fn no_notice() -> Notice {
    notice(0, "", "")
}

fn fact(label: &str, value: impl AsRef<str>, tone: i32) -> Fact {
    Fact {
        label: text(label),
        value: text(value),
        tone,
    }
}

fn plural(count: usize, one: &str, many: &str) -> String {
    format!("{count} {}", if count == 1 { one } else { many })
}

/// One line, at most `limit` characters, with an ellipsis when cut.
pub fn excerpt(value: &str, limit: usize) -> String {
    let single: String = value.split_whitespace().collect::<Vec<_>>().join(" ");
    if single.chars().count() <= limit {
        return single;
    }
    let cut: String = single.chars().take(limit.saturating_sub(1)).collect();
    format!("{}…", cut.trim_end())
}

pub fn short_link(url: &str) -> String {
    url.trim_start_matches("https://")
        .trim_start_matches("http://")
        .trim_start_matches("www.")
        .to_owned()
}

fn search_notice(search: &str) -> Notice {
    notice(
        1,
        "Nada encontrado",
        format!("Nenhum item corresponde a “{search}”. Esc limpa a busca."),
    )
}

/// `None` when the source was read; otherwise the "sem registro" or error notice.
fn source_notice(source: &SourceStatus, what: &str) -> Option<Notice> {
    match &source.state {
        SourceState::Ok => None,
        SourceState::Missing => Some(notice(
            2,
            &format!("Sem registro de {what}"),
            format!("{} não existe neste computador.", source.path),
        )),
        SourceState::Invalid(error) => Some(notice(
            3,
            &format!("Não foi possível ler {what}"),
            format!("{}: {error}", source.path),
        )),
    }
}

fn source_caption(source: &SourceStatus) -> String {
    match &source.state {
        SourceState::Ok => String::new(),
        SourceState::Missing => format!("sem registro · {}", source.path),
        SourceState::Invalid(_) => format!("registro inválido · {}", source.path),
    }
}

fn kpi(label: &str, value: Option<usize>, caption: String, missing_caption: String) -> Kpi {
    Kpi {
        label: text(label),
        value: text(value.map(|count| count.to_string()).unwrap_or_default()),
        caption: text(if value.is_some() {
            caption
        } else {
            missing_caption
        }),
        available: value.is_some(),
    }
}

fn channel_label(channel: Option<&str>) -> &'static str {
    channel
        .and_then(reports::catalog::find)
        .map(|info| info.name)
        .unwrap_or("todos os canais")
}

pub fn kpis(context: &Context) -> Vec<Kpi> {
    let snapshot = context.snapshot;
    let totals = overview::overview(snapshot, context.period, context.channel, context.now, 0);
    let scope = channel_label(context.channel);
    let no_videos = format!("sem pasta de vídeos para {scope}");
    let shorts_total = totals
        .shorts_published
        .zip(totals.shorts_scheduled)
        .map(|(published, scheduled)| published + scheduled);
    let no_shorts = if context
        .channel
        .and_then(reports::catalog::find)
        .is_some_and(|info| !info.has_shorts)
    {
        "este canal não publica shorts".to_owned()
    } else {
        "sem registro de shorts".to_owned()
    };
    let replies = totals
        .x_replies
        .map(|count| format!(" · {}", plural(count, "resposta", "respostas")))
        .unwrap_or_default();
    let x_source = snapshot
        .x
        .sources
        .iter()
        .find(|source| source.label == "X · posts");
    let wa_source = snapshot
        .whatsapp
        .sources
        .iter()
        .find(|source| source.label == "WhatsApp · mensagens recebidas");
    let contacts = snapshot.whatsapp.contacts(Some(context.period)).len();
    let ml = &snapshot.mercadolivre;
    let capture = ml
        .captured_at
        .map(|moment| format!("captura de {}", format_datetime(moment)))
        .unwrap_or_else(|| "captura sem data".into());
    let products_caption = if totals.products == Some(0) {
        format!("nenhuma captura no período · última {capture}")
    } else if ml.query.is_empty() {
        format!("última {capture}")
    } else {
        format!("última {capture} · “{}”", ml.query)
    };
    vec![
        kpi(
            "Vídeos publicados",
            totals.published,
            format!(
                "slot até agora · {scope}{}",
                if totals.drafts > 0 {
                    format!(" · {}", plural(totals.drafts, "rascunho", "rascunhos"))
                } else {
                    String::new()
                }
            ),
            no_videos.clone(),
        ),
        kpi(
            "Vídeos agendados",
            totals.scheduled,
            format!("slot depois de agora · {scope}"),
            no_videos,
        ),
        kpi(
            "Shorts",
            shorts_total,
            format!(
                "{} publicados · {} agendados",
                totals.shorts_published.unwrap_or(0),
                totals.shorts_scheduled.unwrap_or(0)
            ),
            no_shorts,
        ),
        kpi(
            "Posts no X",
            totals.x_posts,
            format!("rede inteira{replies}"),
            x_source.map(source_caption).unwrap_or_default(),
        ),
        kpi(
            "Mensagens no WhatsApp",
            totals.whatsapp_received,
            format!("recebidas · {}", plural(contacts, "contato", "contatos")),
            wa_source.map(source_caption).unwrap_or_default(),
        ),
        kpi(
            "Produtos capturados",
            totals.products,
            products_caption,
            ml.sources.last().map(source_caption).unwrap_or_default(),
        ),
    ]
}

fn kind_label(kind: VideoKind) -> &'static str {
    match kind {
        VideoKind::Long => "vídeo",
        VideoKind::Short => "short",
    }
}

/// Shown at most; the subtitle tells how many exist in total.
const UPCOMING_ROWS: usize = 50;

pub fn upcoming(context: &Context) -> (Vec<UpcomingRow>, Notice, String) {
    let totals = overview::overview(
        context.snapshot,
        context.period,
        context.channel,
        context.now,
        usize::MAX,
    );
    let matching: Vec<_> = totals
        .upcoming
        .iter()
        .filter(|item| matches(context.search, &[&item.title, item.channel_name]))
        .collect();
    let summary = match matching.len() {
        0 => String::new(),
        total if total > UPCOMING_ROWS => {
            format!("{UPCOMING_ROWS} de {total} agendados · ↑ ↓ para navegar")
        }
        total => format!(
            "{} · ↑ ↓ para navegar",
            plural(total, "agendado", "agendados")
        ),
    };
    let rows: Vec<UpcomingRow> = matching
        .iter()
        .take(UPCOMING_ROWS)
        .map(|item| UpcomingRow {
            when: text(format_slot(item.slot)),
            relative: text(format_relative(item.slot, context.now)),
            channel: text(item.channel_name),
            title: text(&item.title),
            kind: text(kind_label(item.kind)),
        })
        .collect();
    let state = if !rows.is_empty() {
        no_notice()
    } else if !context.search.is_empty() && !totals.upcoming.is_empty() {
        search_notice(context.search)
    } else {
        notice(
            1,
            "Nenhum agendamento futuro",
            format!(
                "Nenhum upload com slot depois de agora em {}.",
                channel_label(context.channel)
            ),
        )
    };
    (rows, state, summary)
}

fn binding_view(binding: &Binding) -> (String, i32) {
    match binding {
        Binding::Bound { label, .. } => (format!("vinculado · {label}"), 1),
        Binding::Mismatch { .. } => ("ID de canal divergente".into(), 3),
        Binding::Unbound => ("sem vínculo no registro".into(), 0),
    }
}

fn card(context: &Context, summary: &ChannelSummary) -> ChannelCard {
    let (binding, binding_tone) = binding_view(&summary.binding);
    let from_history = context
        .snapshot
        .channel(summary.slug)
        .is_some_and(|data| data.community.from_history);
    let (community, community_tone) = match &summary.community_last {
        None => ("Comunidade: sem registro".to_owned(), 0),
        Some(entry) if entry.state == "posted" => (
            format!(
                "Comunidade: último post {} · {} no período{}",
                entry
                    .at
                    .map(format_datetime)
                    .unwrap_or_else(|| "sem data".into()),
                summary.community_in_period,
                if from_history {
                    ""
                } else {
                    " (só o último registro)"
                }
            ),
            0,
        ),
        Some(entry) => (
            format!(
                "Comunidade: publicação {} em {} — verificar antes de repetir",
                if entry.state == "unconfirmed" {
                    "não confirmada"
                } else {
                    "iniciada"
                },
                entry
                    .at
                    .map(format_datetime)
                    .unwrap_or_else(|| "sem data".into())
            ),
            2,
        ),
    };
    ChannelCard {
        slug: text(summary.slug),
        name: text(summary.name),
        handle: text(summary.handle),
        binding: text(binding),
        binding_tone,
        available: summary.available,
        published: text(summary.counts.published.to_string()),
        scheduled: text(summary.counts.scheduled.to_string()),
        drafts: text(summary.counts.drafts.to_string()),
        last_title: text(
            summary
                .last_published
                .as_ref()
                .map(|(title, _)| excerpt(title, 60))
                .unwrap_or_default(),
        ),
        last_when: text(
            summary
                .last_published
                .as_ref()
                .map(|(_, slot)| format_slot(*slot))
                .unwrap_or_else(|| "nenhum publicado".into()),
        ),
        next_title: text(
            summary
                .next_scheduled
                .as_ref()
                .map(|(title, _)| excerpt(title, 60))
                .unwrap_or_default(),
        ),
        next_when: text(
            summary
                .next_scheduled
                .as_ref()
                .map(|(_, slot)| format_relative(*slot, context.now))
                .unwrap_or_else(|| "nenhum agendado".into()),
        ),
        community: text(community),
        community_tone,
    }
}

pub fn channel_cards(context: &Context) -> (Vec<ChannelCard>, Vec<&'static str>, Notice) {
    let summaries = overview::channel_summaries(context.snapshot, context.period, context.now);
    let visible: Vec<&ChannelSummary> = summaries
        .iter()
        .filter(|summary| {
            matches(
                context.search,
                &[summary.name, summary.handle, summary.slug],
            )
        })
        .collect();
    let state = if visible.is_empty() {
        search_notice(context.search)
    } else {
        no_notice()
    };
    (
        visible
            .iter()
            .map(|summary| card(context, summary))
            .collect(),
        visible.iter().map(|summary| summary.slug).collect(),
        state,
    )
}

fn state_kind(state: VideoState) -> i32 {
    match state {
        VideoState::Published => 0,
        VideoState::Scheduled => 1,
        VideoState::Draft => 2,
    }
}

pub fn channel_detail(
    context: &Context,
    slug: &str,
) -> Option<(ChannelCard, Vec<VideoRow>, Notice)> {
    let summaries = overview::channel_summaries(context.snapshot, context.period, context.now);
    let summary = summaries.iter().find(|summary| summary.slug == slug)?;
    let data = context.snapshot.channel(slug)?;
    let videos =
        overview::channel_videos(context.snapshot, slug, Some(context.period), context.now);
    let rows: Vec<VideoRow> = videos
        .iter()
        .filter(|(video, _)| matches(context.search, &[&video.title, &video.video_id]))
        .map(|(video, state)| VideoRow {
            title: text(&video.title),
            when: text(
                video
                    .slot
                    .map(format_slot)
                    .unwrap_or_else(|| "sem slot".into()),
            ),
            state: text(state.label()),
            state_kind: state_kind(*state),
            link: text(short_link(&video.link())),
        })
        .collect();
    let state = if let Some(problem) = source_notice(&data.runs.source, "vídeos deste canal") {
        problem
    } else if !rows.is_empty() {
        no_notice()
    } else if !videos.is_empty() {
        search_notice(context.search)
    } else {
        notice(
            1,
            "Nenhum vídeo neste período",
            format!(
                "Nada agendado ou publicado em {}. Mude o período na Visão geral.",
                context.period.label()
            ),
        )
    };
    Some((card(context, summary), rows, state))
}

pub struct ShortsView {
    pub rows: Vec<ShortRow>,
    pub notice: Notice,
    pub summary: String,
    pub missing_thumbs: Vec<PathBuf>,
}

pub fn shorts(context: &Context, thumbs: &HashMap<PathBuf, Image>) -> ShortsView {
    let all = overview::shorts(context.snapshot, context.now);
    let mut missing_thumbs = Vec::new();
    let rows: Vec<ShortRow> = all
        .iter()
        .filter(|(video, _)| matches(context.search, &[&video.title]))
        .map(|(video, state)| {
            let thumb = video.thumbnail.as_ref().and_then(|path| {
                let image = thumbs.get(path).cloned();
                if image.is_none() {
                    missing_thumbs.push(path.clone());
                }
                image
            });
            ShortRow {
                title: text(&video.title),
                when: text(
                    video
                        .slot
                        .map(format_slot)
                        .unwrap_or_else(|| "sem slot".into()),
                ),
                state: text(state.label()),
                state_kind: state_kind(*state),
                link: text(short_link(&video.link())),
                has_thumb: thumb.is_some(),
                thumb: thumb.unwrap_or_default(),
            }
        })
        .collect();
    let source = context
        .snapshot
        .channels
        .iter()
        .find_map(|data| data.shorts.as_ref())
        .map(|shorts| &shorts.source);
    let state = match source.and_then(|source| source_notice(source, "shorts")) {
        Some(problem) => problem,
        None if !rows.is_empty() => no_notice(),
        None if !all.is_empty() => search_notice(context.search),
        None => notice(
            1,
            "Nenhum short registrado",
            "A pasta de shorts do Zaflas está vazia.",
        ),
    };
    let counts = overview::count_states(
        all.iter().map(|(video, _)| *video),
        context.period,
        context.now,
    );
    let summary = format!(
        "{} e {} em {} · Zaflas publica shorts às 09:00 e 18:00 quando solicitado.",
        plural(counts.published, "publicado", "publicados"),
        plural(counts.scheduled, "agendado", "agendados"),
        context.period.label()
    );
    ShortsView {
        rows,
        notice: state,
        summary,
        missing_thumbs,
    }
}

fn account_facts(account: Option<&NetworkAccount>, source: Option<&SourceStatus>) -> Vec<Fact> {
    let mut facts = Vec::new();
    match (account, source.map(|source| &source.state)) {
        (Some(account), _) if account.logged_in() => facts.push(fact("Sessão", "conectada", 1)),
        (Some(account), _) => facts.push(fact(
            "Sessão",
            if account.state.is_empty() {
                "estado desconhecido"
            } else {
                account.state.as_str()
            },
            2,
        )),
        (None, Some(SourceState::Invalid(_))) => facts.push(fact("Sessão", "registro inválido", 3)),
        (None, _) => facts.push(fact("Sessão", "não conectada", 2)),
    }
    if let Some(account) = account {
        let profile = [account.display_name.as_str(), account.handle.as_str()]
            .iter()
            .filter(|value| !value.is_empty())
            .copied()
            .collect::<Vec<_>>()
            .join(" · ");
        if !profile.is_empty() {
            facts.push(fact("Perfil", profile, 0));
        }
        facts.push(fact(
            "Verificada em",
            account
                .verified()
                .map(format_datetime)
                .unwrap_or_else(|| "—".into()),
            0,
        ));
    }
    facts
}

pub struct XView {
    pub facts: Vec<Fact>,
    pub kpis: Vec<Kpi>,
    pub rows: Vec<XPostRow>,
    pub notice: Notice,
}

pub fn x(context: &Context) -> XView {
    let report = &context.snapshot.x;
    let source = |label: &str| report.sources.iter().find(|source| source.label == label);
    let mut facts = account_facts(report.account.as_ref(), source("X · sessão"));
    if source("X · agenda (texto dos posts)").is_some_and(|agenda| !agenda.is_available()) {
        facts.push(fact("Agenda", "sem agenda: textos indisponíveis", 2));
    }
    let (posted, other) = report.replies_in(context.period);
    let replies_source = source("X · respostas");
    let discovery_source = source("X · discovery");
    let kpis = vec![
        kpi(
            "Posts no período",
            report
                .posts_available()
                .then(|| report.posts_in(context.period)),
            "publicados, sem contar excluídos".into(),
            source("X · posts").map(source_caption).unwrap_or_default(),
        ),
        kpi(
            "Respostas no período",
            report.replies_available().then_some(posted),
            if other > 0 {
                format!("{} sem confirmação", other)
            } else {
                "todas confirmadas".into()
            },
            replies_source.map(source_caption).unwrap_or_default(),
        ),
        kpi(
            "Discovery",
            discovery_source
                .filter(|source| source.is_available())
                .map(|_| report.discovery_items),
            report
                .discovery_at
                .map(|moment| format!("candidatos da busca de {}", format_datetime(moment)))
                .unwrap_or_else(|| "busca sem data".into()),
            discovery_source.map(source_caption).unwrap_or_default(),
        ),
    ];
    let listed = report.posts_listed_in(context.period);
    let rows: Vec<XPostRow> = listed
        .iter()
        .filter(|post| matches(context.search, &[&post.text, &post.id]))
        .map(|post| {
            let (state, tone) = match post.state.as_str() {
                "posted" => ("publicado", 1),
                "deleted" => ("excluído", 0),
                "started" | "unconfirmed" => ("não confirmado", 2),
                _ => ("desconhecido", 0),
            };
            XPostRow {
                when: text(
                    post.posted_at
                        .map(format_datetime)
                        .unwrap_or_else(|| "sem data".into()),
                ),
                text: text(if post.text.is_empty() {
                    format!("{} · texto fora da agenda", post.id)
                } else {
                    format!("{} · {}", post.id, excerpt(&post.text, 140))
                }),
                link: text(short_link(&post.url)),
                state: text(state),
                state_kind: tone,
            }
        })
        .collect();
    let state = match source("X · posts").and_then(|source| source_notice(source, "posts no X")) {
        Some(problem) => problem,
        None if !rows.is_empty() => no_notice(),
        None if !listed.is_empty() => search_notice(context.search),
        None => notice(
            1,
            "Nenhum post neste período",
            format!("Nenhum post do X em {}.", context.period.label()),
        ),
    };
    XView {
        facts,
        kpis,
        rows,
        notice: state,
    }
}

pub struct WhatsAppView {
    pub facts: Vec<Fact>,
    pub rules_label: String,
    pub rules: Vec<String>,
    pub rows: Vec<ContactRow>,
    pub notice: Notice,
}

pub fn whatsapp(context: &Context) -> WhatsAppView {
    let report = &context.snapshot.whatsapp;
    let source = |label: &str| report.sources.iter().find(|source| source.label == label);
    let mut facts = account_facts(report.account.as_ref(), source("WhatsApp · sessão"));
    let sends = report.sends_in(context.period);
    if !sends.is_empty() {
        let summary = sends
            .iter()
            .map(|(state, count)| format!("{count} {state}"))
            .collect::<Vec<_>>()
            .join(" · ");
        facts.push(fact("Envios no período", summary, 0));
    }
    let (rules_label, rules) = match &report.rules {
        Some(rules) if rules.mode == "allow" => (
            format!(
                "permitir só {}",
                plural(rules.contacts.len(), "contato", "contatos")
            ),
            rules.contacts.clone(),
        ),
        Some(rules) if rules.mode == "block" => (
            format!(
                "bloquear {}",
                plural(rules.contacts.len(), "contato", "contatos")
            ),
            rules.contacts.clone(),
        ),
        Some(rules) => (format!("modo {}", rules.mode), rules.contacts.clone()),
        None => ("sem regras salvas".into(), Vec::new()),
    };
    let contacts = report.contacts(Some(context.period));
    let rows: Vec<ContactRow> = contacts
        .iter()
        .filter(|contact| matches(context.search, &[&contact.chat, &contact.last_text]))
        .map(|contact| ContactRow {
            contact: text(&contact.chat),
            when: text(
                contact
                    .last_at
                    .map(format_datetime)
                    .unwrap_or_else(|| contact.message_at.clone()),
            ),
            text: text(excerpt(&contact.last_text, 120)),
            count: text(plural(contact.count, "mensagem", "mensagens")),
            allowed: contact.allowed,
        })
        .collect();
    let events = source("WhatsApp · mensagens recebidas");
    let state = match events.and_then(|events| source_notice(events, "mensagens recebidas")) {
        Some(problem) => problem,
        None if !rows.is_empty() => no_notice(),
        None if !contacts.is_empty() => search_notice(context.search),
        None => notice(
            1,
            "Nenhuma mensagem neste período",
            format!(
                "O listener não registrou mensagens em {}.",
                context.period.label()
            ),
        ),
    };
    WhatsAppView {
        facts,
        rules_label,
        rules,
        rows,
        notice: state,
    }
}

pub fn mercadolivre(context: &Context) -> (Vec<Fact>, Vec<ProductRow>, Notice) {
    let report = &context.snapshot.mercadolivre;
    let mut facts = account_facts(report.account.as_ref(), report.sources.first());
    if let Some(moment) = report.captured_at {
        facts.push(fact("Última captura", format_datetime(moment), 0));
    }
    if !report.query.is_empty() {
        facts.push(fact("Busca", format!("“{}”", report.query), 0));
    }
    let rows: Vec<ProductRow> = report
        .products
        .iter()
        .filter(|product| matches(context.search, &[&product.title, &product.brand]))
        .map(|product| ProductRow {
            title: text(&product.title),
            price: text(format_price(product.price, &product.currency)),
            commission: text(&product.commission),
            brand: text(&product.brand),
        })
        .collect();
    let state = match report
        .sources
        .last()
        .and_then(|source| source_notice(source, "produtos capturados"))
    {
        Some(problem) => problem,
        None if !rows.is_empty() => no_notice(),
        None if !report.products.is_empty() => search_notice(context.search),
        None => notice(
            1,
            "Nenhum produto na última captura",
            "products.json não tem produtos.",
        ),
    };
    (facts, rows, state)
}

fn status_view(session: &SessionInfo) -> (String, i32) {
    match session.status.as_str() {
        "logged-in" => ("conectada".into(), 1),
        "configurado" => ("configurado".into(), 1),
        "não conectado" => ("não conectada".into(), 2),
        "login-required" => ("login necessário".into(), 2),
        "sem navegador" => ("sem navegador".into(), 2),
        other => (other.to_owned(), 0),
    }
}

pub fn sessions(all: &[SessionInfo], search: &str, root: &Path) -> (Vec<SessionRow>, Vec<usize>) {
    let mut rows = Vec::new();
    let mut indices = Vec::new();
    for (index, session) in all.iter().enumerate() {
        if !matches(
            search,
            &[
                &session.label,
                &session.network,
                &session.channel,
                &session.status,
            ],
        ) {
            continue;
        }
        let (status, status_tone) = status_view(session);
        let activity = if session.running {
            match session.mode.as_str() {
                "hidden" => "navegador ativo (oculto)",
                "visible" => "navegador ativo (visível)",
                _ => "navegador ativo",
            }
        } else {
            "navegador parado"
        };
        // YouTube profiles store the bound channel ID; show the channel name when it is known.
        let channel = reports::catalog::CHANNELS
            .iter()
            .find(|info| info.channel_id == session.channel)
            .map(|info| info.name.to_owned())
            .unwrap_or_else(|| session.channel.clone());
        rows.push(SessionRow {
            id: text(&session.id),
            label: text(&session.label),
            network: text(&session.network),
            channel: text(channel),
            status: text(status),
            status_tone,
            detail: text(match time::parse_timestamp(&session.detail) {
                Some(moment) => format!("verificada em {}", format_datetime(moment)),
                None if session.detail.is_empty() => "—".to_owned(),
                None => session.detail.clone(),
            }),
            key: text(&session.key),
            scope: text(&session.scope),
            actionable: session.supports_actions(),
            running: session.running,
            activity: text(activity),
            command: text(
                manager_core::actions::command_preview(root, session, "open")
                    .map(|command| format!("Executa: {command}"))
                    .unwrap_or_default(),
            ),
        });
        indices.push(index);
    }
    (rows, indices)
}

pub fn sources(snapshot: &Snapshot, search: &str) -> Vec<SourceRow> {
    snapshot
        .sources()
        .iter()
        .filter(|source| matches(search, &[&source.label, &source.path]))
        .map(|source| {
            let (state, state_kind) = match &source.state {
                SourceState::Ok => ("ok".to_owned(), 0),
                SourceState::Missing => ("ausente".to_owned(), 1),
                SourceState::Invalid(error) => (format!("inválido: {}", excerpt(error, 40)), 2),
            };
            let records = if source.skipped > 0 {
                format!("{} (+{} ignorado)", source.records, source.skipped)
            } else {
                source.records.to_string()
            };
            SourceRow {
                label: text(&source.label),
                path: text(&source.path),
                state: text(state),
                state_kind,
                records: text(records),
            }
        })
        .collect()
}

pub fn login_banner(snapshot: &Snapshot) -> String {
    snapshot
        .login_request
        .as_ref()
        .map(|request| {
            format!(
                "Perfil {} desde {}{}. Conclua o login na janela visível; o aviso some na próxima verificação.",
                if request.profile.is_empty() { "?" } else { request.profile.as_str() },
                request.at.map(format_datetime).unwrap_or_else(|| "data desconhecida".into()),
                if request.reason.is_empty() {
                    String::new()
                } else {
                    format!(" ({})", excerpt(&request.reason, 80))
                }
            )
        })
        .unwrap_or_default()
}

pub fn now() -> NaiveDateTime {
    time::now()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn excerpts_are_single_line_and_bounded() {
        assert_eq!(excerpt("um\ndois   três", 40), "um dois três");
        assert_eq!(excerpt("abcdefghij", 5), "abcd…");
        assert_eq!(short_link("https://youtu.be/x"), "youtu.be/x");
    }
}
