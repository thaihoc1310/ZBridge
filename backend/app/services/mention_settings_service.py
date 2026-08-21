from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MentionClassifierSettings
from app.schemas.api import MentionClassifierSettingsResponse, MentionClassifierSettingsUpdate
from app.services.mention_rules import DEFAULT_MENTION_SKIP_PHRASES, normalize_skip_phrases

GLOBAL_SETTINGS_ID = 1


async def get_or_create_mention_settings(db: AsyncSession) -> MentionClassifierSettings:
    settings = await db.get(MentionClassifierSettings, GLOBAL_SETTINGS_ID)
    if settings is None:
        settings = MentionClassifierSettings(
            id=GLOBAL_SETTINGS_ID,
            ai_classifier_enabled=True,
            bare_mention_requires_response=True,
            skip_phrases=list(DEFAULT_MENTION_SKIP_PHRASES),
        )
        db.add(settings)
        await db.flush()
    return settings


def mention_settings_response(
    settings: MentionClassifierSettings,
) -> MentionClassifierSettingsResponse:
    return MentionClassifierSettingsResponse(
        ai_classifier_enabled=settings.ai_classifier_enabled,
        bare_mention_requires_response=settings.bare_mention_requires_response,
        skip_phrases=list(settings.skip_phrases),
        updated_at=settings.updated_at,
    )


async def get_mention_settings(db: AsyncSession) -> MentionClassifierSettingsResponse:
    settings = await get_or_create_mention_settings(db)
    await db.commit()
    await db.refresh(settings)
    return mention_settings_response(settings)


async def save_mention_settings(
    db: AsyncSession, data: MentionClassifierSettingsUpdate
) -> MentionClassifierSettingsResponse:
    settings = await get_or_create_mention_settings(db)
    settings.ai_classifier_enabled = data.ai_classifier_enabled
    settings.bare_mention_requires_response = data.bare_mention_requires_response
    settings.skip_phrases = normalize_skip_phrases(data.skip_phrases)
    await db.commit()
    await db.refresh(settings)
    return mention_settings_response(settings)
