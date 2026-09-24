"""Seed lexicon: category -> (Tamil stems, English regexes, polysemy notes).

Tamil is agglutinative, so Tamil terms are substring stems. A hit is only a
*candidate*; polysemous stems are flagged so they are checked against commentary.
"""

LEXICON = {
    "sun": {
        "ta": ["ஞாயிறு", "கதிரவ", "சூரிய", "பரிதி", "ஆதவ"],
        "en": [r"\bsun\b", r"\bsunlight\b", r"\bsolar\b"],
        "poly": {"கதிரவ": "kadir also = ear of grain"},
    },
    "moon": {
        "ta": ["திங்கள்", "நிலா", "சந்திர", "மதி"],
        "en": [r"\bmoon", r"\blunar\b"],
        "poly": {"மதி": "mathi also = intellect/wisdom (very common)"},
    },
    "sky_stars": {
        "ta": ["வான்", "விண்", "வானம்", "விண்மீன்", "கோள்", "உடு", "தாரகை"],
        "en": [r"\bsky\b", r"\bheaven", r"\bstars?\b", r"\bfirmament\b", r"\bplanet"],
        "poly": {"வான்": "also heaven as afterlife/rain-giver", "கோள்": "also 'grasp/seize'", "உடு": "also 'wear'"},
    },
    "rain_water": {
        "ta": ["மழை", "முகில்", "மேகம்", "நீர்", "கடல்", "ஆறு"],
        "en": [r"\brain", r"\bclouds?\b", r"\bwater\b", r"\bocean\b", r"\bsea\b", r"\bflood"],
        "poly": {"ஆறு": "also 'six' / 'way'", "நீர்": "also 'quality/nature'"},
    },
    "light_fire": {
        "ta": ["ஒளி", "சுடர்", "ஒளிர்", "தீ", "வெப்ப", "விளக்கு"],
        "en": [r"\blight\b", r"\bradian", r"\bflame", r"\bfire\b", r"\bheat\b", r"\blamp\b", r"\bglow"],
        "poly": {"ஒளி": "also fame/glory", "விளக்கு": "lamp used as metaphor for virtue"},
    },
    "time_season": {
        "ta": ["பருவம்", "காலம்", "இரவு", "பகல்", "ஆண்டு", "நாள்"],
        "en": [r"\bseason", r"\bnight\b", r"\bday\b", r"\bdawn\b", r"\bdusk\b", r"\byear"],
        "poly": {"காலம்": "also 'opportunity/right time' (very common)", "நாள்": "also generic 'day/life-span'"},
    },
    "direction_earth": {
        "ta": ["திசை", "வடக்கு", "தெற்கு", "கிழக்கு", "மேற்கு", "நிலம்", "மண்", "உலகு", "உலகம்", "மலை"],
        "en": [r"\bnorth", r"\bsouth", r"\beast\b", r"\bwest\b", r"\bearth\b", r"\bmountain", r"\bdirection"],
        "poly": {"உலகு": "'world' usually means people/society", "உலகம்": "same", "மண்": "soil / also 'burial'"},
    },
    "vibration_sound": {
        "ta": ["அதிர்", "ஒலி", "இசை", "நாதம்", "ஓசை", "அலை"],
        "en": [r"\bvibrat", r"\bresonan", r"\bsound\b", r"\bmusic", r"\bwave", r"\btrembl", r"\becho"],
        "poly": {"ஒலி": "sound/sound of speech", "அலை": "wave / also 'wander'", "இசை": "also 'fame' (Kural 'isai' = renown)"},
    },
    "cosmos_origin": {
        "ta": ["பூதம்", "ஐம்பூத", "உயிர்", "ஆதி", "பகவன்", "இறை", "தோன்று"],
        "en": [r"\bcosmos\b", r"\buniverse\b", r"\belement", r"\borigin", r"\bcreation\b", r"\bprimal\b"],
        "poly": {"உயிர்": "life/soul, very common", "தோன்று": "to appear / arise"},
    },
}
