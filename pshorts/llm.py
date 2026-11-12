"""DeepSeek: choosing fragments, titles and subtitle translation."""
import json
import urllib.request

API = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

SELECT_RULES = (
    "You select YouTube Shorts fragments from a spiritual talk (pravachanam). "
    "The transcript is machine speech recognition with timecodes in seconds; Sanskrit quotes may be misspelled. "
    "Each fragment is one complete thought of {min_s}-{max_s} seconds; it starts with a clear sentence and ends on a conclusion. "
    "Prefer parables or real-life stories, episodes from the Itihasas, definitions through Sanskrit words, clear rules of dharma. "
    "Snap start and end to segment boundaries. Skip the opening invocation. "
    "Return JSON only: {{\"fragments\":[{{\"start\":sec,\"end\":sec,\"title_en\":\"...\",\"title_ru\":\"...\","
    "\"accent_en\":\"one word of title_en\",\"accent_ru\":\"one word of title_ru\","
    "\"why\":\"parable|itihasa|sanskrit definition|rule\",\"summary_en\":\"2-4 sentences\",\"summary_ru\":\"2-4 sentences\","
    "\"sanskrit_terms\":[\"IAST\"]}}]}}. {count} Order by time. "
    "Titles: 2-5 words. The accent word is the thematic word, never a Sanskrit word. Sanskrit in IAST."
)

TRANSLATE_RULES = {
    "en": ("Translate subtitle chunks of a {src} spiritual talk into clear modern English. "
           "Keep the speaker's voice; do not add explanations. Sanskrit words in IAST without italics "
           "(dharma, kīrti, pāpa-bhīti, Rāma, Sītā, vānaras). "),
    "ru": ("Переведи фрагменты субтитров духовной беседы ({src}) на ясный современный русский. "
           "Сохраняй голос говорящего, ничего не добавляй. Санскрит в русской передаче: ś→щ, ṣ→ш "
           "(щастры, ащрам; Бхишма, кшатрии без изменений). «Гуру», «Свамиджи», имена Бога — с заглавной. "
           "Не используй слова «пожертвование», «жертвователь» — только «дарение», «даритель». "),
}
TRANSLATE_TAIL = (
    "Write in subtitle style: short and easy to read, about 2.2 words per second of the chunk at most; "
    "drop spoken fillers and repetitions (\"look\", \"there, there\", repeated words) but keep every idea. "
    "Chunks are consecutive; a sentence may continue into the next chunk — translate so the chunks read "
    "naturally in order, keeping each chunk's meaning in that chunk. Machine transcription errors are possible: "
    "translate by sense. Return JSON only: {\"chunks\":{\"<id>\":\"translation\"}} with every id present."
)


def chat(api_key, system, user, temperature=0.3, timeout=300):
    body = json.dumps({"model": MODEL, "temperature": temperature,
                       "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode("utf-8")
    req = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + api_key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return json.loads(data["choices"][0]["message"]["content"])


def transcript_text(segments):
    return "\n".join("[%d-%d] %s" % (s["start"], s["end"], s["text"]) for s in segments)


def select_fragments(api_key, segments, count=None, min_s=35, max_s=120, glossary=""):
    cnt = ("Give exactly %d fragments." % count) if count else "Give every good fragment you find (usually 5-8)."
    system = SELECT_RULES.format(min_s=min_s, max_s=max_s, count=cnt)
    if glossary:
        system += "\nApproved spellings of terms (always use these): " + glossary
    return chat(api_key, system, transcript_text(segments)).get("fragments", [])


def translate_chunks(api_key, chunks, lang, src_lang_name="Telugu", glossary=""):
    system = TRANSLATE_RULES[lang].format(src=src_lang_name) + TRANSLATE_TAIL
    if glossary:
        system += "\nApproved spellings / corrections (always follow): " + glossary
    user = json.dumps({str(i): c["text"] for i, c in enumerate(chunks)}, ensure_ascii=False)
    out = chat(api_key, system, user).get("chunks", {})
    return [out.get(str(i), "") for i in range(len(chunks))]


SUBS_RULES = (
    "You make subtitles for a vertical Short cut from a {src} spiritual talk. Input: the fragment's words, "
    "numbered, from machine speech recognition (errors are possible; words may be cut). Also given: context "
    "before and after the fragment, for understanding only.\n"
    "Group consecutive words into subtitles that follow sentences and natural sense breaks (about 2-6 seconds of "
    "speech each, never splitting a word group mid-thought). Cover every word index from 0 to the last, in order, "
    "with no gaps or overlaps. For each subtitle write {langs}.\n"
    "Translate by sense, not word by word. Telugu idioms: render their meaning (e.g. నలుగురు / నలుగురి కోసం = "
    "'people, others, for the sake of others', not 'four'). Subtitle style: short, easy to read, about 2.2 words "
    "per second at most; drop fillers and repetitions but keep every idea.\n"
    "If the recognised text there looks wrong or the meaning is unclear, put a short English reason in \"flag\" "
    "(else empty string).\n"
    "ENDING: the Short must end where the speaker's thought is fully concluded (a closing statement such as "
    "'this is dharma', a moral, or a summary), never on a half-finished argument. The words after index "
    "{last_core} are a possible continuation: include them only as far as needed to reach that conclusion, and "
    "stop right after it. Report the index of the final word in \"last\". Also check that the last subtitle "
    "translates the final words (closing phrases are easy to drop).\n"
    "Return JSON only: {{\"last\":k,\"subs\":[{{\"from\":i,\"to\":j,{fields}\"flag\":\"\"}}]}} "
    "covering words 0..last."
)
LANG_SPEC = {
    "en": ("\"en\": clear modern English; Sanskrit in IAST without italics (dharma, kīrti, Rāma, Sītā)", "\"en\":\"...\","),
    "ru": ("\"ru\": ясный современный русский; санскрит по правилу ś→щ, ṣ→ш (щастры, ащрам; Бхишма, кшатрии); "
           "«Гуру», «Свамиджи», имена Бога с заглавной; вместо «пожертвование/жертвователь» — «дарение/даритель»",
           "\"ru\":\"...\","),
}


def subtitles_request(words, langs=("en", "ru"), src_lang_name="Telugu", before="", after="", glossary="",
                      last_core=None):
    """Build the system and user messages for semantic subtitle segmentation + translation.
    `words` may include a tail after the selected end (index > last_core) so the ending can be extended."""
    if last_core is None:
        last_core = len(words) - 1
    system = SUBS_RULES.format(src=src_lang_name, langs="; ".join(LANG_SPEC[l][0] for l in langs),
                               fields="".join(LANG_SPEC[l][1] for l in langs), last_core=last_core)
    if glossary:
        system += "\nApproved spellings and corrections (always follow): " + glossary
    user = ("CONTEXT BEFORE: " + before + "\n\nFRAGMENT WORDS:\n" +
            " ".join("%d:%s" % (i, w["w"]) for i, w in enumerate(words)) +
            "\n\nCONTEXT AFTER: " + after)
    return system, user


def subtitles_from_reply(reply, words, langs=("en", "ru")):
    """Turn DeepSeek's reply into timed subtitles; repair gaps/overlaps."""
    last = len(words) - 1
    if "last" in reply:
        try:
            last = max(0, min(int(reply["last"]), last))
        except (TypeError, ValueError):
            pass
    subs, nxt = [], 0
    for s in sorted(reply.get("subs", []), key=lambda x: int(x.get("from", 0))):
        if int(s.get("from", 0)) > last:
            continue
        a, b = max(int(s.get("from", 0)), nxt), min(int(s.get("to", 0)), last)
        if b < a:
            continue
        if a > nxt and subs:  # a gap: attach missing words to the previous subtitle
            subs[-1]["to"] = a - 1
        item = {"from": a, "to": b, "flag": s.get("flag", "") or ""}
        for l in langs:
            item[l] = (s.get(l) or "").strip()
        subs.append(item)
        nxt = b + 1
    if subs and subs[-1]["to"] < last:
        subs[-1]["to"] = last
    for s in subs:
        s["start"] = words[s["from"]]["s"]
        s["end"] = words[s["to"]]["e"]
        s["orig"] = " ".join(w["w"] for w in words[s["from"]:s["to"] + 1])
    for a, b in zip(subs, subs[1:]):  # keep each subtitle until the next one starts
        a["end"] = b["start"]
    return subs


def make_subtitles(api_key, words, langs=("en", "ru"), **kw):
    system, user = subtitles_request(words, langs, **kw)
    return subtitles_from_reply(chat(api_key, system, user), words, langs)
