"""Built-in templates for common services: typing a known name fills in category and billing cycle.

Prices are deliberately left out: they differ by country, plan and over time.
"""

from dataclasses import dataclass

from subtrack.domain.models import BillingCycle, Category


@dataclass(frozen=True)
class ServiceTemplate:
    name: str
    category: Category
    billing_cycle: BillingCycle = BillingCycle.MONTHLY


_S, _M, _SW, _C, _G, _U, _F, _N, _O = (
    Category.STREAMING, Category.MUSIC, Category.SOFTWARE, Category.CLOUD, Category.GAMING,
    Category.UTILITIES, Category.FITNESS, Category.NEWS, Category.OTHER,
)

TEMPLATES: list[ServiceTemplate] = [
    # Video streaming
    ServiceTemplate("Netflix", _S), ServiceTemplate("Disney+", _S), ServiceTemplate("HBO Max", _S),
    ServiceTemplate("Amazon Prime Video", _S), ServiceTemplate("Apple TV+", _S),
    ServiceTemplate("YouTube Premium", _S), ServiceTemplate("SkyShowtime", _S), ServiceTemplate("Voyo", _S),
    ServiceTemplate("Paramount+", _S), ServiceTemplate("Crunchyroll", _S), ServiceTemplate("Twitch Turbo", _S),
    # Music and audio
    ServiceTemplate("Spotify", _M), ServiceTemplate("Spotify Family", _M), ServiceTemplate("Apple Music", _M),
    ServiceTemplate("YouTube Music", _M), ServiceTemplate("Tidal", _M), ServiceTemplate("Deezer", _M),
    ServiceTemplate("Audible", _M),
    # Cloud storage
    ServiceTemplate("iCloud+", _C), ServiceTemplate("Google One", _C), ServiceTemplate("Dropbox", _C),
    ServiceTemplate("OneDrive", _C), ServiceTemplate("Proton Drive", _C),
    # Software and AI
    ServiceTemplate("Microsoft 365", _SW, BillingCycle.YEARLY), ServiceTemplate("Adobe Creative Cloud", _SW),
    ServiceTemplate("ChatGPT Plus", _SW), ServiceTemplate("Claude Pro", _SW), ServiceTemplate("GitHub Copilot", _SW),
    ServiceTemplate("JetBrains All Products", _SW, BillingCycle.YEARLY), ServiceTemplate("Canva Pro", _SW),
    ServiceTemplate("Notion", _SW), ServiceTemplate("1Password", _SW, BillingCycle.YEARLY),
    ServiceTemplate("Bitwarden Premium", _SW, BillingCycle.YEARLY), ServiceTemplate("NordVPN", _SW, BillingCycle.YEARLY),
    ServiceTemplate("Proton VPN", _SW), ServiceTemplate("Duolingo Super", _SW, BillingCycle.YEARLY),
    ServiceTemplate("Domain name", _SW, BillingCycle.YEARLY), ServiceTemplate("Web hosting", _SW, BillingCycle.YEARLY),
    # Gaming
    ServiceTemplate("Xbox Game Pass", _G), ServiceTemplate("PlayStation Plus", _G, BillingCycle.YEARLY),
    ServiceTemplate("Nintendo Switch Online", _G, BillingCycle.YEARLY), ServiceTemplate("EA Play", _G),
    ServiceTemplate("Ubisoft+", _G), ServiceTemplate("GeForce NOW", _G),
    # Utilities and home
    ServiceTemplate("Mobile phone plan", _U), ServiceTemplate("Internet", _U), ServiceTemplate("Electricity", _U),
    ServiceTemplate("Gas", _U), ServiceTemplate("Water", _U), ServiceTemplate("TV cable", _U),
    ServiceTemplate("Home insurance", _U, BillingCycle.YEARLY), ServiceTemplate("Car insurance (RCA)", _U, BillingCycle.YEARLY),
    # Fitness
    ServiceTemplate("Gym", _F), ServiceTemplate("Strava", _F, BillingCycle.YEARLY), ServiceTemplate("7card", _F),
    # News
    ServiceTemplate("The New York Times", _N), ServiceTemplate("The Economist", _N), ServiceTemplate("Medium", _N),
    ServiceTemplate("Substack", _N),
    # Other
    ServiceTemplate("Amazon Prime", _O, BillingCycle.YEARLY), ServiceTemplate("Glovo Prime", _O),
    ServiceTemplate("Bolt Plus", _O), ServiceTemplate("Revolut Premium", _O), ServiceTemplate("Patreon", _O),
]

_BY_NAME = {template.name.lower(): template for template in TEMPLATES}


def find(name: str) -> ServiceTemplate | None:
    """The template whose name matches exactly (ignoring case and spaces), if any."""
    return _BY_NAME.get(name.strip().lower())


def names() -> list[str]:
    return [template.name for template in TEMPLATES]
