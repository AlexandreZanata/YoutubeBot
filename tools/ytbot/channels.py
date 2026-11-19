"""Per-channel profiles for prompts, language, duration and video style."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Channel:
    slug: str
    name: str
    handle: str
    channel_id: str
    prompts: str
    background: str
    language: str
    min_article_chars: int
    article_retry: str
    max_article_chars: int = 0
    narration_volume: float = 2.0
    slots: tuple[int, ...] = (0, 12)
    interval_days: int = 1


CHANNELS = {
    "zaflas": Channel(
        slug="zaflas",
        name="Zaflas",
        handle="@zaflas",
        channel_id="UCi2aftoK7vlS3A6OozMHXKg",
        prompts="zaflas_agro",
        background="agro",
        language="pt-BR",
        min_article_chars=26000,
        article_retry=(
            "Target narration length: 4,000 to 4,800 Brazilian Portuguese words, "
            "about 25 to 35 minutes at the channel's current narration pace. Preserve the "
            "fixed Zaflas Agro opening identification and final sign-off."
        ),
        max_article_chars=100000,
        slots=(12,),
    ),
    "fallem-prince": Channel(
        slug="fallem-prince",
        name="fallem prince",
        handle="@fallemprince",
        channel_id="UCc288lF54UDCCGhTKIkr7BQ",
        prompts="fallem_prince",
        background="fallem_prince",
        language="en",
        min_article_chars=40000,
        article_retry="Target narration length: at least 6,500 words.",
        slots=(0, 6, 12, 18),
    ),
    "infinite-random-worlds": Channel(
        slug="infinite-random-worlds",
        name="Infinite Random Worlds",
        handle="@InfiniteRandomWorlds",
        channel_id="UCY3Zp50I6Y6semQQccJxRPg",
        prompts="infinite_random_worlds",
        background="thumbnail",
        language="en",
        min_article_chars=30000,
        article_retry=(
            "Target narration length: 4,500 to 6,000 English words, about 32 to 43 "
            "minutes at a measured pace. Each story must use a unique world and cast."
        ),
        max_article_chars=85000,
        slots=(12,),
    ),
    "vocal-pages": Channel(
        slug="vocal-pages",
        name="Vocal Pages",
        handle="@VocalPages01",
        channel_id="UCm13oIPS1W43j9BYo0kewcQ",
        prompts="vocal_pages",
        background="vocal_pages",
        language="en",
        min_article_chars=58000,
        article_retry=(
            "Reduce the narration to at most 70,000 characters, about 10,000 words. Cut "
            "whole sections instead of summarizing. Keep one theme and the quiet ending."
        ),
        max_article_chars=130000,
        slots=(0,),
        interval_days=2,
    ),
    "reflection": Channel(
        slug="reflection",
        name="the word of reflection",
        handle="@thewordofreflection",
        channel_id="UCISw6UDaFINPRuuMr0s7tpA",
        prompts="reflection",
        background="whispers_from_heaven",
        language="en",
        min_article_chars=13000,
        article_retry=(
            "Target narration length: 2,200 to 2,500 English words, about 14 to 16 "
            "minutes. Keep the same character and moment."
        ),
        max_article_chars=48000,
        slots=(5, 17),
    ),
    "zanata": Channel(
        slug="zanata",
        name="zanata",
        handle="@zanatareal",
        channel_id="UCx0AE-elCyDhfY0d1hQIwdw",
        prompts="zanata",
        background="black",
        language="en",
        min_article_chars=50000,
        article_retry=(
            "Target narration length: 8,000 to 8,500 English words, about 50 to 55 "
            "minutes. Keep the same book and author."
        ),
        max_article_chars=100000,
        slots=(16,),
    ),
    "sepia-atlas": Channel(
        slug="sepia-atlas",
        name="Sepia Atlas",
        handle="@SepiaAtlas",
        channel_id="UCJNamJBuijKJ5G7CgLgd7EQ",
        prompts="sepia_atlas",
        background="thumbnail",
        language="en",
        min_article_chars=13000,
        article_retry=(
            "Target narration length: 1,900 to 3,200 English words (15 to 25 minutes "
            "at the channel's 0.9x documentary pace, tolerance up to 40 minutes / "
            "~5,100 words). Keep the same subject, sources and documentary arc; "
            "never pad with filler."
        ),
        max_article_chars=36000,
        slots=(21,),
        interval_days=2,
    ),
    "bathylora": Channel(
        slug="bathylora",
        name="Bathylora",
        handle="@Bathylora",
        channel_id="UCxuhkOi4CDDStvQFpRGsoXA",
        prompts="bathylora",
        background="thumbnail",
        language="en",
        min_article_chars=13000,
        article_retry=(
            "Target narration length: 1,900 to 3,200 English words (15 to 25 minutes "
            "at the channel's 0.9x documentary pace, tolerance up to 40 minutes / "
            "~5,100 words). Keep the same ocean science subject, verified sources and "
            "documentary arc; never pad with filler."
        ),
        max_article_chars=36000,
        slots=(21,),
        interval_days=2,
    ),
    "midnight-tales": Channel(
        slug="midnight-tales",
        name="Midnight Tales",
        handle="@Midnight1Tales",
        channel_id="UCLukC7RYzHlXHjtnlkbe4Vw",
        prompts="midnight_tales",
        background="thumbnail",
        language="en",
        min_article_chars=40000,
        article_retry=(
            "Target narration length: 6,500 to 9,000 English words, about 45 to 65 "
            "minutes at the channel's calm pace. Keep the same characters and place."
        ),
        max_article_chars=90000,
        slots=(21,),
        interval_days=2,
    ),
    "whispers-from-heaven": Channel(
        slug="whispers-from-heaven",
        name="Whispers From Heaven",
        handle="@WhispersFromHeaven1",
        channel_id="UCEE9qAtucy5OZcjvcyytu4w",
        prompts="whispers_from_heaven",
        background="whispers_from_heaven",
        language="en",
        min_article_chars=13000,
        article_retry=(
            "Target narration length: 2,400 to 2,800 words, about 15 to 17 "
            "minutes at a calm pace."
        ),
    ),
}


def get(slug: str) -> Channel:
    channel = CHANNELS.get(slug)
    if channel is None:
        options = ", ".join(sorted(CHANNELS))
        raise SystemExit(f"unknown channel: {slug}. Options: {options}")
    return channel


def apply(slug: str) -> Channel:
    from . import config
    channel = get(slug)
    config.apply_channel(channel)
    return channel
