"""
English and Arabic for the buyer-facing client.

Demo mode and the admin page stay English: they show the pipeline's own artifacts,
stage names and column headers, and translating those hides what a reviewer came to read.
"""

from __future__ import annotations

LANGS = ("en", "ar")

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "nav.home": "Home",
        "nav.chat": "Chat",
        "nav.inventory": "Inventory",
        "nav.admin": "Admin",
        "err.backend": "Backend not reachable at {url}. Start it with:  uv run uvicorn main:app --reload",
        "home.title": "Find your next car.",
        "home.sub": "Ask in plain English or Arabic, compare listings, and book a viewing.",
        "home.what": "What it does",
        "home.ask_label": "Ask about a car",
        "home.ask_ph": "Try: a white SUV under AED 100k with warranty",
        "home.ask_btn": "Ask",
        "home.review_t": "Reviewing this build?",
        "home.review_btn": "Open demo mode",
        "home.browse": "Browse the inventory",
        "home.live": "live",
        "home.frozen": "frozen",
        "stat.listings": "listings, both sheets merged",
        "stat.retrieval": "retrieval mode",
        "stat.model": "model behind the replies",
        "stat.clock": "booking clock",
        "chat.thinking": "Thinking",
        "chat.done": "Done",
        "chat.failed": "Failed",
        "chat.error": "Sorry, that did not go through. {error}",
        "chat.welcome_back": "Welcome back, {name}.",
        "chat.welcome_back_sub": "Pick up where you left off, or start something new.",
        "chat.hi_name": "Hi {name}, what are you looking for?",
        "chat.hi": "What are you looking for?",
        "chat.hi_sub": "Search the inventory, compare listings, or book a viewing.",
        "chat.hi_sub_new": "Search the inventory, compare listings, or book a viewing. Say hi with your name and I will remember you next time.",
        "chat.more_on": "More on the",
        "chat.where_left": "Where you left off",
        "chat.or_try": "Or try one of these",
        "chat.input_known": "Ask about a car, or say hi",
        "chat.input_new": "Ask about a car, or say hi and tell me your name",
        "card.no_price": "Price not listed",
        "card.per_mo": "or {amount}/mo",
        "card.mo_only": "{amount}/mo · cash price not listed",
        "card.km": "{km} km",
        "badge.warranty": "Warranty",
        "badge.inspected": "dubizzle inspected",
        "badge.new": "Brand new",
        "btn.ask": "Ask about it",
        "btn.book": "Book a viewing",
        "side.demo": "Demo mode",
        "side.demo_help": "Shows the trace, prompt, retrieval, grounding, and memory under every reply, plus the admin page.",
        "side.admin_flag": "Admin needs DEBUG_ENDPOINTS=true on the backend",
        "side.language": "Language",
        "acct.title": "Your account",
        "acct.intro": "Tell me your name and I will remember your searches, the cars you liked, and your bookings next time. Saying hi in the chat works too.",
        "acct.name": "Name",
        "acct.continue": "Continue",
        "acct.signed_in": "Signed in as **{name}**",
        "acct.contact": "**Contact details**",
        "acct.contact_note": "Saved straight to the backend, never through the model.",
        "acct.phone": "Phone (UAE mobile)",
        "acct.email": "Email",
        "acct.save": "Save",
        "acct.bookings": "**Bookings**",
        "acct.no_bookings": "No viewings yet. Ask the chat to book one.",
        "acct.not_you": "Not you?",
        "acct.your_name": "Your name",
        "acct.switch": "Switch",
        "acct.forget": "Forget me",
        "acct.forget_help": "Deletes your profile, searches, likes, bookings, and contact details.",
        "acct.forgotten": "Forgotten. Your profile, searches, likes, bookings, and contact details are gone.",
        "inv.title": "Inventory",
    },
    "ar": {
        "nav.home": "الرئيسية",
        "nav.chat": "المحادثة",
        "nav.inventory": "المعرض",
        "nav.admin": "الإدارة",
        "err.backend": "تعذّر الوصول إلى الخادم على {url}. شغّله بالأمر:  uv run uvicorn main:app --reload",
        "home.title": "اعثر على سيارتك القادمة.",
        "home.sub": "اسأل بالعربية أو بالإنجليزية، قارن بين الإعلانات، واحجز معاينة.",
        "home.what": "ماذا يفعل",
        "home.ask_label": "اسأل عن سيارة",
        "home.ask_ph": "جرّب: سيارة دفع رباعي بيضاء بأقل من 100 ألف درهم مع ضمان",
        "home.ask_btn": "اسأل",
        "home.review_t": "تراجع هذا المشروع؟",
        "home.review_btn": "افتح وضع العرض",
        "home.browse": "تصفّح المعرض",
        "home.live": "مباشر",
        "home.frozen": "مثبّت",
        "stat.listings": "إعلاناً، من الجدولين معاً",
        "stat.retrieval": "طريقة البحث",
        "stat.model": "النموذج خلف الردود",
        "stat.clock": "ساعة الحجز",
        "chat.thinking": "جارٍ التفكير",
        "chat.done": "تم",
        "chat.failed": "أخفق",
        "chat.error": "عذراً، لم تتم العملية. {error}",
        "chat.welcome_back": "أهلاً بعودتك يا {name}.",
        "chat.welcome_back_sub": "أكمل من حيث توقفت، أو ابدأ بحثاً جديداً.",
        "chat.hi_name": "مرحباً {name}، عن أي سيارة تبحث؟",
        "chat.hi": "عن أي سيارة تبحث؟",
        "chat.hi_sub": "ابحث في المعرض، قارن بين الإعلانات، أو احجز معاينة.",
        "chat.hi_sub_new": "ابحث في المعرض، قارن بين الإعلانات، أو احجز معاينة. قل مرحباً واذكر اسمك وسأتذكّرك في المرة القادمة.",
        "chat.more_on": "المزيد عن",
        "chat.where_left": "حيث توقفت",
        "chat.or_try": "أو جرّب أحد هذه",
        "chat.input_known": "اسأل عن سيارة، أو قل مرحباً",
        "chat.input_new": "اسأل عن سيارة، أو قل مرحباً واذكر اسمك",
        "card.no_price": "السعر غير مذكور",
        "card.per_mo": "أو {amount} شهرياً",
        "card.mo_only": "{amount} شهرياً · السعر النقدي غير مذكور",
        "card.km": "{km} كم",
        "badge.warranty": "ضمان",
        "badge.inspected": "مفحوصة من دوبيزل",
        "badge.new": "جديدة",
        "btn.ask": "اسأل عنها",
        "btn.book": "احجز معاينة",
        "side.demo": "وضع العرض",
        "side.demo_help": "يعرض المسار والتعليمات والبحث والتحقق والذاكرة تحت كل رد، إضافة إلى صفحة الإدارة.",
        "side.admin_flag": "صفحة الإدارة تحتاج DEBUG_ENDPOINTS=true على الخادم",
        "side.language": "اللغة",
        "acct.title": "حسابك",
        "acct.intro": "أخبرني باسمك وسأتذكّر عمليات بحثك والسيارات التي أعجبتك وحجوزاتك في المرة القادمة. يكفي أن تقول مرحباً في المحادثة.",
        "acct.name": "الاسم",
        "acct.continue": "متابعة",
        "acct.signed_in": "مسجّل الدخول باسم **{name}**",
        "acct.contact": "**بيانات التواصل**",
        "acct.contact_note": "تُحفظ مباشرة في الخادم، ولا تمر عبر النموذج أبداً.",
        "acct.phone": "الهاتف (رقم إماراتي)",
        "acct.email": "البريد الإلكتروني",
        "acct.save": "حفظ",
        "acct.bookings": "**الحجوزات**",
        "acct.no_bookings": "لا توجد معاينات بعد. اطلب من المحادثة أن تحجز واحدة.",
        "acct.not_you": "لست أنت؟",
        "acct.your_name": "اسمك",
        "acct.switch": "تبديل",
        "acct.forget": "انسَني",
        "acct.forget_help": "يحذف ملفك وعمليات بحثك والسيارات التي أعجبتك وحجوزاتك وبيانات تواصلك.",
        "acct.forgotten": "تم النسيان. حُذف ملفك وعمليات بحثك والسيارات التي أعجبتك وحجوزاتك وبيانات تواصلك.",
        "inv.title": "المعرض",
    },
}

# The card shows closed vocabularies, so they translate from a table rather than a model call.
ENUMS: dict[str, str] = {
    "suv": "دفع رباعي",
    "sedan": "سيدان",
    "coupe": "كوبيه",
    "convertible": "مكشوفة",
    "hatchback": "هاتشباك",
    "pickup": "بيك أب",
    "van": "فان",
    "wagon": "ستيشن",
    "truck_chassis": "شاصي",
    "gcc": "خليجي",
    "japan": "ياباني",
    "us": "أمريكي",
    "euro": "أوروبي",
    "korean": "كوري",
    "petrol": "بنزين",
    "diesel": "ديزل",
    "hybrid": "هجينة",
    "electric": "كهربائية",
    "automatic": "أوتوماتيك",
    "manual": "عادي",
    "white": "أبيض",
    "black": "أسود",
    "silver": "فضي",
    "grey": "رمادي",
    "gray": "رمادي",
    "blue": "أزرق",
    "red": "أحمر",
    "green": "أخضر",
    "brown": "بني",
    "beige": "بيج",
    "gold": "ذهبي",
    "orange": "برتقالي",
    "yellow": "أصفر",
    "purple": "بنفسجي",
    "maroon": "عنابي",
}


def t(key: str, lang: str = "en", **fmt: object) -> str:
    """A missing key falls back to English and then to the key itself, so a gap never crashes a page."""
    table = STRINGS.get(lang) or STRINGS["en"]
    text = table.get(key) or STRINGS["en"].get(key) or key
    return text.format(**fmt) if fmt else text


NOT_STATED = frozenset({"null", "none", "n/a", "na", "nil", "unknown", "not specified", "-"})


def stated(value: object) -> str:
    """A field the model filled in with the word for empty is empty, and shows as nothing."""
    s = str(value or "").strip()
    return "" if s.lower() in NOT_STATED else s


def enum_label(value: object, lang: str = "en") -> str:
    """Card facts come from closed sets, so Arabic needs no model call. Anything else is left as is."""
    s = stated(value)
    if lang != "ar" or not s:
        return s
    return ENUMS.get(s.strip().lower(), s)
