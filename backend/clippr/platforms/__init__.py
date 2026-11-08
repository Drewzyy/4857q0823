from .base import OAuthConnector
from .meta import MetaConnector
from .tiktok import TikTokConnector
from .youtube import YouTubeConnector

CONNECTORS: dict[str, OAuthConnector] = {c.key: c for c in (YouTubeConnector(), TikTokConnector(), MetaConnector())}

# Which connector logs in a given destination platform.
CONNECTOR_FOR_DESTINATION = {"youtube": "youtube", "tiktok": "tiktok", "facebook": "meta", "instagram": "meta"}
DESTINATION_PLATFORMS = ("tiktok", "instagram", "youtube", "facebook")
