"""Vertical religious Shorts with one generated background image per short."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import account, assets, catalog, channels, chat, config, logic, render, runtime, youtube
from .accounts_store import AccountStore

CHANNELS = {
    "reflection": {
        "upload": "reflection",
        "hours": (8, 20),
        "hashtags": "#shorts #faith #bible #prayer #hope #god",
        "tags": "faith, bible, prayer, hope, god, short, devotional, scripture",
        "topics": (
            "Hannah: When You Have No Words Left to Pray",
            "Elijah in the Cave: When the Storm Is Not God",
            "Peter's Nets: When Obedience Comes Before the Catch",
            "The Widow's Oil: When Little Is All You Have",
            "Joseph in Prison: When the Promise Feels Forgotten",
            "The Prodigal Son: When You Come Home With Nothing",
            "The Woman at the Well: When Someone Sees You Whole",
            "Paul's Thorn: When the Answer Is No",
            "The Friends Who Dug Through the Roof",
            "Stephen at the Stones: When Forgiveness Costs Everything",
            "The Centurion's Faith: When Authority Meets Trust",
            "Zacchaeus in the Tree: When You Need to See and Be Seen",
            "The Woman Who Touched His Hem: When Faith Acts Before Words",
            "Thomas After the Resurrection: When Doubt Becomes a Door",
            "The Ethiopian Eunuch: When a Stranger Opens the Book",
        ),
    },
    "zaflas": {
        "upload": "zaflas",
        "hours": (9, 18),
        "hashtags": "#zaflasagro #agricultura #agro #shorts #gestaorural",
        "tags": "Zaflas Agro, agricultura, agronegócio, gestão rural, solo, lavoura, pecuária",
        "topics": (
            "Por que a palhada protege o solo do sol?",
            "Como saber se o calcário reagiu no solo?",
            "O que a umidade do grão faz com o preço?",
            "Por que o bezerro desmama mais leve?",
            "Quando a pulverização perde eficiência?",
            "Por que o pH do solo muda depois da calagem?",
            "Como o milho responde ao nitrogênio em cobertura?",
            "O que a compactação do solo faz com a raiz?",
            "Quando o gado precisa de suplementação mineral?",
            "Por que a colheitadeira perde grãos na barra de corte?",
        ),
    },
    "zanata": {
        "upload": "zanata",
        "hours": (9,),
        "hashtags": "#books #philosophy #psychology #summary #shorts",
        "tags": "book summary, philosophy, psychology, sociology, ideas, short",
        "topics": (
            "Why We Perform: Goffman and the Masks We Wear",
            "The Tyranny of the Should: Karen Horney on the Ideal Self",
            "Why a Scapegoat Unites a Crowd: René Girard",
            "The Banality of Evil: Arendt on Ordinary People",
            "The Denial of Death: Becker on Why We Build",
            "Why Good People Obey: Milgram and Authority",
            "The Elephant and the Rider: Haidt on Moral Intuition",
            "Flow: Csikszentmihalyi on the State of Absorption",
            "Man's Search for Meaning: Frankl in the Camp",
            "The Social Animal: How Groups Shape the Self",
            "The Crowd: Le Bon on How Groups Think",
            "Thinking, Fast and Slow: Kahneman on the Two Minds",
            "The Life of the Mind: Arendt on Thinking",
            "The Wisdom of Insecurity: Watts on Letting Go",
            "Escape from Freedom: Fromm on Why We Surrender",
        ),
    },
    "whispers-from-heaven": {
        "upload": "youtube-2",
        "hours": (9, 21),
        "hashtags": "#shorts #faith #bible #prayer #hope #god",
        "tags": "faith, bible, prayer, hope, god, short, devotional, scripture",
        "topics": (
            "When the Night Feels Longer Than Your Faith",
            "The Shepherd Who Leaves the Ninety-Nine",
            "A Prayer You Whisper Is Still Heard",
            "The Peace That Does Not Depend on the Storm",
            "He Gathers the Weary, One by One",
            "When You Feel Forgotten, He Has Not Left",
            "The God Who Runs to Meet You",
            "A Lamp for the Darkest Room",
            "The Hands That Hold Tomorrow",
            "Rest for the Ones Who Carry Everyone",
            "When the Answer Comes Later Than You Hoped",
            "He Walks With You Through the Valley",
            "A Prayer for the Ones You Cannot Reach",
            "The Peace That Holds in the Waiting",
            "When Your Faith Is Small but Real",
        ),
    },
    "fallem-prince": {
        "upload": "legacy",
        "hours": (21,),
        "hashtags": "#shorts #fantasy #darkfantasy #story #audiobook",
        "tags": "dark fantasy, story, audiobook, short, fiction, folklore",
        "topics": (
            "The Bell That Rings Only for the Dead",
            "A Knight Who Forgot His Own Name",
            "The Mirror in the Abandoned Chapel",
            "The Cartographer of a Forest That Moves",
            "The King Who Traded His Shadow",
            "The Last Lantern on the Northern Road",
            "A Debt Collected at Midnight",
            "The Castle That Remembers Its Guests",
            "The Smith Who Forged a Silence",
            "The Wolf at the Edge of the Feast",
        ),
    },
    "infinite-random-worlds": {
        "upload": "infinite",
        "hours": (9,),
        "hashtags": "#shorts #scifi #story #worldbuilding #audiobook",
        "tags": "speculative fiction, science fiction, story, audiobook, short, worldbuilding",
        "topics": (
            "On a World of Endless Stairs, One City Learns to Climb",
            "The Ocean That Falls Upward",
            "A Library Where Books Age Instead of People",
            "The Last Rain on a Planet of Dust",
            "A City That Only Exists at Low Tide",
            "The Boy Who Delivers Messages Between Two Moons",
            "The Garden That Grows Memories",
            "The Train That Never Reaches the Station",
            "A World Where Night Lasts a Generation",
            "The Map That Redraws Itself Every Morning",
        ),
    },
    "vocal-pages": {
        "upload": "vocal",
        "hours": (21,),
        "hashtags": "#shorts #essay #reflection #story #audiobook",
        "tags": "reflective essay, story, audiobook, short, psychology, humanity",
        "topics": (
            "The Chair Left Empty at Dinner",
            "What We Keep in the Drawer",
            "The Kindness We Do Not Remember",
            "A Stranger Who Knew Your Name",
            "The House That Feels Smaller",
            "Why We Tell the Same Story",
            "The Cost of Always Being Fine",
            "A Letter You Never Sent",
            "The Quiet After the Argument",
            "What the Hands Remember",
        ),
    },
    "midnight-tales": {
        "upload": "midnight",
        "hours": (9,),
        "interval_days": 2,
        "hashtags": "#shorts #sleepstory #fiction #bedtimestory #audiobook",
        "tags": "sleep story, fiction, audiobook, short, bedtime story, cozy",
        "topics": (
            "The Lamplighter Who Waited for One Last Window",
            "The Library That Returns Lost Things",
            "A Night Train to a Town Without a Name",
            "The Keeper of the Frozen Clock",
            "The Harbor Where Ships Arrive at Dawn",
            "The Inn at the Edge of the Snow",
            "The Gardener of the Moonlit Greenhouse",
            "The Postman of the Sleeping Village",
            "The Star That Only Appears in Winter",
            "The Door That Opens on Quiet Nights",
        ),
    },
    "sepia-atlas": {
        "upload": "sepia",
        "hours": (9,),
        "interval_days": 2,
        "hashtags": "#shorts #history #archivalphotography #documentary #sepiaatlas",
        "tags": "history, documentary, archival photography, historical photos, short",
        "topics": (
            "The Photograph That Saved a Vanished Town",
            "What a 1900 Street Photograph Really Shows",
            "The Machine That Changed Every Kitchen",
            "A Lost Railway Station in One Frame",
            "The Faces of Ellis Island",
            "When Every City Had a Horse Market",
            "The Last Photograph of the General Store",
            "The Invention Nobody Remembers",
            "A Farm Family in 1895",
            "The Day the Electric Light Arrived",
        ),
    },
    "bathylora": {
        "upload": "bathylora",
        "hours": (21,),
        "interval_days": 2,
        "hashtags": "#shorts #deepsea #oceanexploration #marinebiology #bathylora",
        "tags": "deep sea, ocean exploration, marine biology, documentary, ocean science, short",
        "topics": (
            "The Bigfin Squid Filmed in the Deep Gulf of Mexico",
            "How Dumbo Octopuses Move Three Miles Below the Surface",
            "Life Beside a 700-Degree Hydrothermal Vent",
            "Why Glass Sponges Live for Thousands of Years",
            "What Actually Happens to Light Below 1,000 Meters",
            "The Deep-Sea Anglerfish and Its Bacterial Lantern",
            "How Giant Isopods Survive Years Between Meals",
            "Underwater Lakes of Brine on the Ocean Floor",
            "How ROV Deep Discoverer Explores the Abyss",
            "The Bioluminescent Alarm Systems of Deep-Sea Jellyfish",
        ),
    },
}

# Fresh queues for the next distribution round; kept separate so the curated
# originals above stay readable.
QUEUE_EXTENSION = {
    "reflection": (
        "Mary at the Tomb: When Grief Looks for Jesus",
        "The Persistent Widow: When Prayer Feels Unanswered",
        "Bartimaeus by the Road: When You Cry Out Anyway",
        "The Servant Girl's Courage: When Small Faith Speaks",
        "Jonah Under the Plant: When Mercy Offends",
        "The Road to Emmaus: When Scripture Walks Beside You",
    ),
    "zaflas": (
        "Por que a rotação de pastagem evita verminose?",
        "Como a época de semeadura muda o estande?",
        "O que o teor de proteína diz sobre a silagem?",
        "Por que o trator patina na curva de nível?",
        "Quando o fósforo fica indisponível no solo?",
        "Como o clima afeta a qualidade do algodão?",
    ),
    "zanata": (
        "The Prince by Machiavelli: How Power Keeps Itself",
        "Leviathan by Hobbes: Why People Trade Freedom for Order",
        "Silent Spring by Rachel Carson: The Cost of a Quiet Morning",
        "The Selfish Gene by Dawkins: Why Cooperation Can Be Selfish",
        "The Human Condition by Arendt: What Work and Action Mean",
        "Nickel and Dimed by Ehrenreich: When Work Does Not Pay",
    ),
    "fallem-prince": (
        "The Lamplighter Who Never Reached the Last Street",
        "The Cartographer of a Country That Forgot Its Name",
        "The Bell That Rang Only for the Drowned",
        "The Widow Who Sold the Sea",
        "The Clockmaker's Unfinished Confession",
        "The Orchard Where No Bird Sang",
    ),
    "infinite-random-worlds": (
        "On a world where shadows arrive before their owners, a boy must hide his own.",
        "In a city built inside a sleeping whale, a mechanic hears the heart slow down.",
        "On a moon where every lie becomes visible, a diplomat must tell the truth.",
        "In a country where roads remember everyone who walks them, a courier is followed.",
        "On a planet where winter is a living creature, a farmer must negotiate with it.",
        "In a village where the sea visits once a year, a girl waits for the tide to speak.",
    ),
    "vocal-pages": (
        "The Unsent Birthday Message",
        "The Coffee Cup on the Windowsill",
        "The Friend You Outgrew",
        "The Job You Left at the Right Time",
        "The Apology You Never Got",
        "The Sunday Evening Feeling",
    ),
    "midnight-tales": (
        "The Lighthouse That Kept a Winter Diary",
        "The Gardener of the Moonlit Greenhouse",
        "The Library Beneath the Lake",
        "The Inn Where the Road Ends",
        "The Shepherd of the Sleeping Hills",
        "The House That Learned to Breathe",
    ),
    "sepia-atlas": (
        "The Last Streetcar of 1910",
        "A Summer on the Farm in 1905",
        "The Photographer of Ellis Island",
        "The Factory Bell at Dawn",
        "The Flood That Changed a Town",
        "The Plain of the 1904 Fair",
    ),
    "bathylora": (
        "The Fish That Waits in the Dark",
        "A Brine Pool on the Seafloor",
        "The Octopus of the Abyssal Plain",
        "What a Whale Fall Feeds",
        "The Glow of a Comb Jelly",
        "The Sound of a Deep-Sea Volcano",
    ),
}
for _slug, _topics in QUEUE_EXTENSION.items():
    CHANNELS[_slug]["topics"] = CHANNELS[_slug]["topics"] + _topics

QUEUE_EXTENSION_2 = {
    "sepia-atlas": (
        "A Boarding House Breakfast in 1905",
        "The Letter That Took Six Weeks to Arrive",
        "When the Circus Came to Town in 1902",
        "The Icebox Before the Refrigerator",
        "A Sunday Drive in 1908",
        "The Corner Drugstore in 1910",
        "The Schoolteacher's One-Room Year",
        "The Flood That Took the Bridge",
        "A Photograph of Main Street, 1904",
        "The Night the Lights Went Out",
    ),
    "bathylora": (
        "The Octopus That Broods for Four Years",
        "A Whale Skeleton Full of Life",
        "The Fish with a Lantern on Its Head",
        "What Lives at Four Thousand Meters?",
        "The Glass Sponge That Filters the Dark",
        "A Brine Pool at the Bottom of the Sea",
        "The Jellyfish That Glows When Touched",
        "The Squid That Lives Without Sunlight",
        "How a Vent Chimney Grows",
        "The Sound of a Deep-Sea Volcano",
    ),
}
for _slug, _topics in QUEUE_EXTENSION_2.items():
    CHANNELS[_slug]["topics"] = CHANNELS[_slug]["topics"] + _topics


QUEUE_EXTENSION_3 = {
    "whispers-from-heaven": (
        "The Widow Who Fed the Prophet First",
        "The Servant Girl Who Spoke the Name",
        "The Well Where Three Generations Waited",
        "The Prison That Could Not Hold the Song",
        "The Table Set for the One Who Left",
    ),
    "midnight-tales": (
        "The Lighthouse Keeper Who Painted the Fog",
        "The Apothecary's Garden of Sleeping Flowers",
        "The Last Tram Through the Snow",
        "The Bookbinder Who Repaired Dreams",
        "The Teahouse at the Edge of the Rain",
    ),
    "zanata": (
        "The Art of War by Sun Tzu: Winning Before the First Battle",
        "Meditations by Marcus Aurelius: The Discipline of the Present",
        "The Republic by Plato: The Price of Justice",
    ),
}
for _slug, _topics in QUEUE_EXTENSION_3.items():
    CHANNELS[_slug]["topics"] = CHANNELS[_slug]["topics"] + _topics



def log(message: str) -> None:
    print(f"[faith-shorts] {message}", flush=True)


def occupied_slots(root: Path) -> set[tuple[int, int, int, int]]:
    slots = set()
    for upload in root.glob("*/upload.json"):
        try:
            data = json.loads(upload.read_text(encoding="utf-8"))
            slot = datetime.strptime(data.get("slot", ""), "%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            continue
        if data.get("scheduled"):
            slots.add((slot.year, slot.month, slot.day, slot.hour))
    return slots


def short_slots(count: int, hours: tuple[int, ...], start: date,
                skip: int = 0,
                occupied: set[tuple[int, int, int, int]] | None = None,
                interval_days: int = 1) -> list[datetime]:
    slots = []
    day = start
    index = 0
    while len(slots) < count + skip:
        for hour in hours:
            slot = datetime.combine(day, dtime(hour=hour))
            if slot > datetime.now() + timedelta(minutes=60) and not (
                    occupied and (slot.year, slot.month, slot.day, slot.hour) in occupied):
                slots.append(slot)
                if len(slots) == count + skip:
                    return slots[skip:]
        day += timedelta(days=interval_days)
        index += 1
    return slots


def background_signature(path: Path) -> int:
    from PIL import Image

    with Image.open(path) as image:
        small = image.convert("L").resize((16, 16), Image.Resampling.LANCZOS)
        pixels = list(small.getdata())
    mean = sum(pixels) / len(pixels)
    return sum(1 << index for index, value in enumerate(pixels) if value > mean)


def similar_background(root: Path, run_dir: Path, limit: int = 24) -> Path | None:
    current = run_dir / "thumbnail.png"
    if not current.is_file():
        return None
    signature = background_signature(current)
    for other in root.glob("*/thumbnail.png"):
        if other.parent == run_dir or not other.is_file():
            continue
        if bin(signature ^ background_signature(other)).count("1") < limit:
            return other
    return None


def ensure_unique_background(gen, run_dir: Path, root: Path) -> None:
    """Every Short owns one image; a near-duplicate is replaced once."""
    for _attempt in range(2):
        duplicate = similar_background(root, run_dir)
        if duplicate is None:
            return
        log(f"background too similar to {duplicate.parent.name}; generating a new scene")
        stamp = int(time.time())
        (run_dir / "thumbnail.png").rename(run_dir / f"thumbnail-similar-{stamp}.png")
        state = run_dir / ".codex-media" / "thumbnail"
        if state.is_dir():
            state.rename(state.with_name(f"thumbnail-attempt-{stamp}"))
        assets.generate_thumbnail(
            gen, run_dir, "short-background",
            variation="Create a clearly different scene from the previous attempt: change the "
                      "place, the objects, the light and the composition.")
    if similar_background(root, run_dir) is not None:
        log("background still resembles another Short; kept for review")


def generate_script(page, topic: str, run_dir: Path) -> str:
    page.goto(config.GPT_URL, timeout=90000)
    page.wait_for_timeout(7000)
    chat.dismiss_notice(page)
    header = config.prompt("shorts.txt")
    language = config.CHANNEL.language if config.CHANNEL else "en"
    if language == "pt-BR":
        header += ("\n\nIDIOMA OBRIGATÓRIO: português do Brasil. Escreva todo o texto falado "
                   "nesse idioma, sem nenhuma palavra em inglês. Responda apenas com a narração.")
    else:
        header += ("\n\nMANDATORY NARRATION LANGUAGE: English. Write the entire spoken short in "
                   "English, regardless of the operator message or the browser language. Return "
                   "only the narration text.")
    chat.send_text(page, header + "\n\nTheme: " + topic)
    log(f"script prompt sent: {topic}")
    chat.wait_for_assistant(page)
    text = chat.clean_article(chat.copy_last(page))
    words = len(text.split())
    if words < 60 or words > 180:
        raise RuntimeError(f"short narration has an unexpected length ({words} words)")
    (run_dir / "short.txt").write_text(text, encoding="utf-8")
    log(f"short saved: {len(text)} chars, {words} words")
    return text


def metadata(topic: str, text: str, spec: dict | None = None) -> dict:
    spec = spec or {}
    hashtags = spec.get("hashtags", "#shorts #faith #bible #prayer #hope #god")
    tags = spec.get("tags", "faith, bible, prayer, hope, god, short, devotional, scripture")
    description = text.strip() + "\n\n" + hashtags + "\n\nTAGS: " + tags
    return {"title": topic + " #Shorts", "description": description, "tags": tags}


def render_short(run_dir: Path) -> Path:
    from src.engine.audio_mixer import get_audio_duration
    from src.engine.subtitle_generator import save_ass_subtitles
    from src.engine.video_composer import render_single_pass_video

    narration = run_dir / "narration.aac"
    duration = get_audio_duration(narration)
    if duration <= 0:
        raise RuntimeError("short narration duration is unknown")
    segments = render.transcribe_narration(narration)
    if not segments:
        raise RuntimeError("short transcription produced no text")
    subtitle = save_ass_subtitles(
        segments, run_dir / "narration.ass", font_size=72, width=1080, height=1920,
        alignment=5, outline_width=5, margin_horizontal=72)
    output = run_dir / "video.mp4"
    ok = render_single_pass_video(
        image_path=run_dir / "thumbnail.png", narr_path=narration, bgm_path=None,
        subtitle_path=subtitle, output_path=output, narr_vol=config.NARRATION_VOLUME,
        bgm_vol=0.0, width=1080, height=1920, fps=30, total_duration=duration,
        background_is_video=False)
    if not ok:
        raise RuntimeError("short render failed")
    log(f"video saved: {output} ({output.stat().st_size} bytes)")
    return output


def published_longs(context) -> list[dict]:
    """Public, processed long videos of the channel, used as Short related links."""
    payload = catalog.fetch_creator_videos(context)
    found: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            try:
                length = int(node.get("lengthSeconds") or 0)
            except (TypeError, ValueError):
                length = 0
            if (node.get("videoId") and length >= 120
                    and node.get("privacy") == "VIDEO_PRIVACY_PUBLIC"
                    and node.get("status") == "VIDEO_STATUS_PROCESSED"):
                found.append({"videoId": node["videoId"], "title": node.get("title", "")})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    seen = set()
    unique = []
    for row in found:
        if row["videoId"] not in seen:
            seen.add(row["videoId"])
            unique.append(row)
    return unique


def link_related_video(context, video_id: str, title: str) -> bool:
    """Attach an already-published long video to a Short in the Studio editor."""
    page = youtube.open_edit(context, video_id)
    try:
        body = " ".join(page.locator("body").inner_text().split())
        if title[:40] in body:
            return True
        opened = False
        for label in ("Related video", "Vídeo relacionado"):
            button = page.get_by_text(label, exact=False)
            if button.count():
                button.first.click()
                page.wait_for_timeout(3500)
                opened = True
                break
        if not opened:
            return False
        search = page.locator("#search-yours")
        if search.count():
            search.first.fill(title[:70])
            page.wait_for_timeout(2500)
        card = page.locator("ytcp-entity-card").filter(has_text=title[:40]).first
        if not card.count():
            return False
        card.click()
        page.wait_for_timeout(2000)
        for name in ("Select", "Selecionar"):
            confirm = page.get_by_role("button", name=name, exact=True)
            if confirm.count() and confirm.last.is_visible():
                confirm.last.click()
                page.wait_for_timeout(1500)
                break
        page.evaluate("()=>document.querySelector('#save')?.click()")
        page.wait_for_timeout(4000)
        page.reload()
        page.wait_for_timeout(7000)
        return title[:40] in " ".join(page.locator("body").inner_text().split())
    finally:
        page.close()


def run(channel_slug: str, count: int = 5, start: date | None = None,
        skip_slots: int = 0, start_index: int = 0,
        *,
        visual_mode: str | None = None,
        video_provider: str | None = None,
        video_model: str | None = None,
        max_credits: float | None = None,
        max_scenes: int | None = None,
        fallback_to_static: bool | None = None,
        dry_run: bool = False) -> list:
    from .shorts_video import assert_channel_policy, assert_shorts_scope
    from .shorts_video.pipeline import render_ai_short
    from .shorts_video.settings import resolve_runtime_settings

    spec = CHANNELS[channel_slug]
    channels.apply(channel_slug)
    resolved = resolve_runtime_settings(
        visual_mode=visual_mode or "static",
        provider=video_provider,
        model=video_model,
        max_credits_per_short=max_credits,
        max_scenes_per_short=max_scenes,
        fallback_to_static=fallback_to_static,
    )
    effective_mode = resolved["visual_mode"]
    assert_shorts_scope("shorts", width=1080, height=1920, visual_mode=effective_mode)
    if effective_mode == "ai-video":
        assert_channel_policy(channel_slug, resolved)

    topics = []
    for candidate in list(spec["topics"])[start_index:]:
        run_dir = config.DATA_DIR / "shorts" / logic.slug(candidate)
        if (run_dir / "upload.json").is_file():
            continue
        topics.append(candidate)
        if len(topics) == count:
            break
    if len(topics) < count:
        raise RuntimeError(f"only {len(topics)} unused Short topics left for {channel_slug}")
    slots = short_slots(len(topics), spec["hours"],
                        start or (date.today() + timedelta(days=1)), skip_slots,
                        occupied_slots(config.DATA_DIR / "shorts"),
                        spec.get("interval_days", 1))
    root = config.DATA_DIR / "shorts"
    if dry_run:
        for topic, slot in zip(topics, slots):
            run_dir = root / logic.slug(topic)
            run_dir.mkdir(parents=True, exist_ok=True)
            short_path = run_dir / "short.txt"
            script_text = short_path.read_text(encoding="utf-8") if short_path.is_file() else topic
            if effective_mode == "ai-video":
                summary = render_ai_short(
                    run_dir,
                    channel_slug,
                    topic,
                    script_text,
                    visual_mode=effective_mode,
                    video_provider=video_provider,
                    video_model=video_model,
                    max_credits_per_short=max_credits,
                    max_scenes=max_scenes,
                    fallback_to_static=fallback_to_static,
                    dry_run=True,
                )
                log(
                    f"dry-run {topic} ({logic.slot_label(slot)}): provider={summary['provider']} "
                    f"model={summary['model']} scenes={summary['scene_count']} "
                    f"est_credits={summary['estimated_credits']} budget={summary['budget_reason']}"
                )
            else:
                log(f"dry-run {topic} ({logic.slot_label(slot)}): mode=static")
        return []

    store = AccountStore()
    store.activate(spec["upload"])
    runtime.start_hidden_chrome()
    upload_cdp = store.account(spec["upload"])["cdp_port"]
    store.activate("legacy")
    runtime.start_hidden_chrome()
    failures = []
    with sync_playwright() as playwright:
        gen_browser, gen = runtime.connect_hidden(playwright)
        upload_browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{upload_cdp}")
        up = upload_browser.contexts[0]
        account.ensure_channel(up)
        longs = published_longs(up)
        used_links: list[str] = []
        runtime.configure_downloads(gen_browser)
        runtime.configure_extension(gen)
        for topic, slot in zip(topics, slots):
            run_dir = root / logic.slug(topic)
            run_dir.mkdir(parents=True, exist_ok=True)
            run_dir.chmod(0o700)
            (run_dir / "topic.txt").write_text(topic, encoding="utf-8")
            logic.set_run_field(run_dir, topic=topic)
            started = time.time()
            page = gen.new_page()
            try:
                text = generate_script(page, topic, run_dir)
                chat.capture_audio(page, gen, run_dir)
            except Exception as error:
                failures.append((topic, str(error)))
                log(f"asset failure for {topic}: {error}")
                page.close()
                continue
            finally:
                try:
                    page.close()
                except Exception:
                    pass
            try:
                assets.generate_thumbnail(gen, run_dir, "short-background")
                ensure_unique_background(gen, run_dir, root)
                ai_result = None
                if effective_mode == "ai-video":
                    ai_result = render_ai_short(
                        run_dir,
                        channel_slug,
                        topic,
                        text,
                        visual_mode=effective_mode,
                        video_provider=video_provider,
                        video_model=video_model,
                        max_credits_per_short=max_credits,
                        max_scenes=max_scenes,
                        fallback_to_static=fallback_to_static,
                        static_fallback_fn=render_short,
                    )
                else:
                    render_short(run_dir)
                meta = metadata(topic, text, spec)
                if ai_result and ai_result.get("visual_mode") == "ai-video":
                    meta["visual_mode"] = "ai-video"
                    meta["video_provider"] = ai_result.get("provider", "")
                    meta["video_model"] = ai_result.get("model", "")
                    meta["synthetic_media_disclosure"] = bool(
                        ai_result.get("synthetic_disclosure_required", True)
                    )
                (run_dir / "metadata.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                youtube.upload_and_schedule_with_context(
                    up, run_dir, meta, slot, custom_thumbnail=False, end_screen=False)
                log(f"scheduled {topic} at {logic.slot_label(slot)} "
                    f"({time.time() - started:.0f}s)")
                try:
                    upload = json.loads((run_dir / "upload.json").read_text(encoding="utf-8"))
                    video_id = upload.get("videoId")
                    if video_id and longs:
                        target = longs[len(used_links) % len(longs)]
                        if link_related_video(up, video_id, target["title"]):
                            used_links.append(target["videoId"])
                            log(f"related {video_id} -> {target['videoId']}")
                        else:
                            log(f"related video not linked for {video_id}")
                except Exception as error:
                    log(f"related video warning for {topic}: {error}")
            except Exception as error:
                failures.append((topic, str(error)))
                log(f"upload/render failure for {topic}: {error}")
    runtime.stop_hidden_chrome()
    return failures

