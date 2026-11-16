"""Supported answer languages and separate saved-answer namespaces."""

from typing import Literal

from .question_match import ANSWER_PIPELINE_VERSION

AnswerLanguage = Literal["en", "hi", "sa", "es", "ta", "te", "ml", "bn"]

LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "sa": "Sanskrit", "es": "Spanish",
    "ta": "Tamil", "te": "Telugu", "ml": "Malayalam", "bn": "Bengali",
}

REFUSALS = {
    "en": "The supplied passages do not confirm the answer to this question.",
    "hi": "दिए गए अंशों से इस प्रश्न के उत्तर की पुष्टि नहीं होती।",
    "sa": "प्रदत्ताः पाठांशाः अस्य प्रश्नस्य उत्तरं न पुष्टयन्ति।",
    "es": "Los pasajes proporcionados no confirman la respuesta a esta pregunta.",
    "ta": "கொடுக்கப்பட்ட பகுதிகள் இந்தக் கேள்விக்கான பதிலை உறுதிப்படுத்தவில்லை.",
    "te": "ఇచ్చిన పాఠ్య భాగాలు ఈ ప్రశ్నకు సమాధానాన్ని నిర్ధారించలేదు.",
    "ml": "നൽകിയ ഭാഗങ്ങൾ ഈ ചോദ്യത്തിനുള്ള ഉത്തരം സ്ഥിരീകരിക്കുന്നില്ല.",
    "bn": "দেওয়া অংশগুলো এই প্রশ্নের উত্তর নিশ্চিত করে না।",
}


def answer_pipeline_version(language: AnswerLanguage) -> str:
    # Preserve all existing English saved answers. The unique index already
    # includes pipeline_version, so each other language gets a separate key.
    return ANSWER_PIPELINE_VERSION if language == "en" else f"{ANSWER_PIPELINE_VERSION}+answer-{language}-v1"
