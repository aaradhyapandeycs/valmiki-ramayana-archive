"""Display-only IAST spellings for reviewed Sanskrit terms in Dutt's text."""
from collections import Counter
import re

GLOSSARY_REFERENCE = (
    "https://claysanskritlibrary.org/book-extras/"
    "ramayana-book-i-boyhood-ancilliaries-glossary-of-important-proper-nouns-and-epithets/"
)

# Keep distinct valid manuscript forms where Dutt's spelling distinguishes them,
# such as Bibhīṣaṇa and Vibhīṣaṇa. Preserve the English plural suffix.
SPELLINGS = {
    "Ahalya": "Ahalyā",
    "Aksha": "Akṣa",
    "Anasuya": "Anasūyā",
    "Anasuyā": "Anasūyā",
    "Angada": "Aṅgada",
    "Ançumat": "Aṃśumat",
    "Ançumān": "Aṃśumān",
    "Asoka": "Aśoka",
    "Asokas": "Aśokas",
    "Ayodhya": "Ayodhyā",
    "Açoka": "Aśoka",
    "Açwapati": "Aśvapati",
    "Açwins": "Aśvins",
    "Bhagiratha": "Bhagīratha",
    "Bharadwaja": "Bharadvāja",
    "Bharadwāja": "Bharadvāja",
    "Bhrigu": "Bhṛgu",
    "Bibhisana": "Bibhīṣaṇa",
    "Bibhishana": "Bibhīṣaṇa",
    "Bibhishaua": "Bibhīṣaṇa",
    "Bibhāndaka": "Bibhāṇḍaka",
    "Brahmaçiras": "Brahmaśiras",
    "Brāhmana": "Brāhmaṇa",
    "Brāhmanas": "Brāhmaṇas",
    "Chitrakuta": "Citrakūṭa",
    "Dacaratha": "Daśaratha",
    "Daksha": "Dakṣa",
    "Dandaka": "Daṇḍaka",
    "Dandakas": "Daṇḍakas",
    "Dasaratha": "Daśaratha",
    "Daçaratha": "Daśaratha",
    "Daçarathas": "Daśarathas",
    "Daçarathee": "Dāśarathi",
    "Daçarātha": "Daśaratha",
    "Dhumrāksha": "Dhūmrākṣa",
    "Dushana": "Dūṣaṇa",
    "Dāçarathi": "Dāśarathi",
    "Ganga": "Gaṅgā",
    "Gangā": "Gaṅgā",
    "Garuda": "Garuḍa",
    "Gavaksha": "Gavākṣa",
    "Gavāksha": "Gavākṣa",
    "Hanuman": "Hanumān",
    "Hanumin": "Hanumān",
    "Hanumln": "Hanumān",
    "Hanumlān": "Hanumān",
    "Hanumāna": "Hanumān",
    "Hauumān": "Hanumān",
    "Ikshwaku": "Ikṣvāku",
    "Ikshwāku": "Ikṣvāku",
    "Ikshwākus": "Ikṣvākus",
    "Ikswāku": "Ikṣvāku",
    "Jambavān": "Jāmbavān",
    "Jambavāna": "Jāmbavān",
    "Janaki": "Jānakī",
    "Jatayu": "Jaṭāyu",
    "Jatāyu": "Jaṭāyu",
    "Jāmbavāna": "Jāmbavān",
    "Jānaki": "Jānakī",
    "Kaikayi": "Kaikeyī",
    "Kaikeyi": "Kaikeyī",
    "Kailaça": "Kailāsa",
    "Kailāça": "Kailāsa",
    "Kakutstha": "Kākutstha",
    "Kaucalyā": "Kausalyā",
    "Kausalya": "Kausalyā",
    "Kauçalya": "Kausalyā",
    "Kauçalyā": "Kausalyā",
    "Kauçika": "Kauśika",
    "Kauçiki": "Kauśikī",
    "Kaçyapa": "Kāśyapa",
    "Keçarin": "Keśarin",
    "Keçini": "Keśinī",
    "Kinçuka": "Kiṃśuka",
    "Kinçukas": "Kiṃśukas",
    "Kishkinda": "Kiṣkindhā",
    "Kishkindha": "Kiṣkindhā",
    "Kishkindhā": "Kiṣkindhā",
    "Koçala": "Kosala",
    "Koçalas": "Kosalas",
    "Kshatriya": "Kṣatriya",
    "Kshatriyas": "Kṣatriyas",
    "Kumbhakarna": "Kumbhakarṇa",
    "Kusa": "Kuśa",
    "Kuça": "Kuśa",
    "Kuçadhwaja": "Kuśadhvaja",
    "Kuçanābha": "Kuśanābha",
    "Kuçika": "Kuśika",
    "Kākustha": "Kākutstha",
    "Kākuthstha": "Kākutstha",
    "Kāçyapa": "Kāśyapa",
    "Lakshamana": "Lakṣmaṇa",
    "Lakshmana": "Lakṣmaṇa",
    "Lakshmi": "Lakṣmī",
    "Lanka": "Laṅkā",
    "Lankā": "Laṅkā",
    "Mahaçwara": "Maheśvara",
    "Maheswara": "Maheśvara",
    "Maheçwara": "Maheśvara",
    "Mahāparshwa": "Mahāpārśva",
    "Mahāparçwa": "Mahāpārśva",
    "Mahāpārcwa": "Mahāpārśva",
    "Mahāpārçwa": "Mahāpārśva",
    "Mahāçanku": "Mahāśaṅku",
    "Maithilee": "Maithilī",
    "Maithili": "Maithilī",
    "Mandodari": "Mandodarī",
    "Manthara": "Mantharā",
    "Maricha": "Mārīca",
    "Mithila": "Mithilā",
    "Māricha": "Mārīca",
    "Narada": "Nārada",
    "Narayana": "Nārāyaṇa",
    "Nila": "Nīla",
    "Niçākara": "Niśākara",
    "Panchavati": "Pañcavaṭī",
    "Paçupati": "Paśupati",
    "Pañchavatī": "Pañcavaṭī",
    "Piçācha": "Piśāca",
    "Piçāchas": "Piśācas",
    "Punarvaçu": "Punarvasu",
    "Pushpaka": "Puṣpaka",
    "Rakshasa": "Rākṣasa",
    "Rakshasas": "Rākṣasas",
    "Rakshasee": "Rākṣasī",
    "Rakshasees": "Rākṣasīs",
    "Rakshasi": "Rākṣasī",
    "Rakshasis": "Rākṣasīs",
    "Rama": "Rāma",
    "Ramayana": "Rāmāyaṇa",
    "Ravana": "Rāvaṇa",
    "Raçmiketu": "Raśmiketu",
    "Rhishyasringa": "Ṛṣyaśṛṅga",
    "Rhishyasriuga": "Ṛṣyaśṛṅga",
    "Rhrishyamuka": "Ṛśyamūka",
    "Rishyamuka": "Ṛśyamūka",
    "Rishyamukha": "Ṛśyamūka",
    "Rishyasringa": "Ṛṣyaśṛṅga",
    "Rishymuka": "Ṛśyamūka",
    "Rākshasa": "Rākṣasa",
    "Rākshasas": "Rākṣasas",
    "Rākshasee": "Rākṣasī",
    "Rākshasees": "Rākṣasīs",
    "Rākshasi": "Rākṣasī",
    "Rākshasis": "Rākṣasīs",
    "Rāmayana": "Rāmāyaṇa",
    "Rāmāyana": "Rāmāyaṇa",
    "Rāvana": "Rāvaṇa",
    "Sachee": "Śacī",
    "Sachi": "Śacī",
    "Sacra": "Śakra",
    "Sakra": "Śakra",
    "Sampati": "Sampāti",
    "Sankara": "Śaṅkara",
    "Sarabhanga": "Śarabhaṅga",
    "Sarayu": "Sarayū",
    "Satrughana": "Śatrughna",
    "Satrughna": "Śatrughna",
    "Satrugna": "Śatrughna",
    "Siddhāçrama": "Siddhāśrama",
    "Sinçapā": "Śiṃśapā",
    "Sita": "Sītā",
    "Sitā": "Sītā",
    "Siva": "Śiva",
    "Sivā": "Śiva",
    "Sudhanwā": "Sudhanvā",
    "Sugrira": "Sugrīva",
    "Sugrirā": "Sugrīva",
    "Sugriva": "Sugrīva",
    "Sugrivā": "Sugrīva",
    "Sumitra": "Sumitrā",
    "Suparna": "Suparṇa",
    "Surpanakha": "Śūrpaṇakhā",
    "Surpanakhā": "Śūrpaṇakhā",
    "Swetā": "Śvetā",
    "Trisanku": "Triśaṅku",
    "Triçanku": "Triśaṅku",
    "Triçiras": "Triśiras",
    "Urmila": "Ūrmilā",
    "Vaidehi": "Vaidehī",
    "Vaiçravana": "Vaiśravaṇa",
    "Vaiçwānara": "Vaiśvānara",
    "Vaiçyas": "Vaiśyas",
    "Valmiki": "Vālmīki",
    "Varuna": "Varuṇa",
    "Vasishtha": "Vasiṣṭha",
    "Vibhishana": "Vibhīṣaṇa",
    "Vishnu": "Viṣṇu",
    "Viswāmitra": "Viśvāmitra",
    "Vivaçwān": "Vivasvān",
    "Viçwakarma": "Viśvakarma",
    "Viçwakarmā": "Viśvakarmā",
    "Viçwamitra": "Viśvāmitra",
    "Viçwarupa": "Viśvarūpa",
    "Viçwāmitra": "Viśvāmitra",
    "Viçāla": "Viśāla",
    "Viçālā": "Viśālā",
    "Yaksha": "Yakṣa",
    "Yakshas": "Yakṣas",
    "Yatāyu": "Jaṭāyu",
    "açoka": "aśoka",
    "açokas": "aśokas",
    "kuça": "kuśa",
    "çālas": "śālas",
}

# Negated Unicode letters keep replacements within exact tokens. An apostrophe,
# hyphen, or underscore still permits English possessives and source emphasis.
WORD = r"[^\W\d_]"
TOKEN = re.compile(
    rf"(?<!{WORD})(?:Brahma|{'|'.join(map(re.escape, SPELLINGS))})(?!{WORD})"
)
REVIEW_ONLY = {"Brahma", "Hanumān", "Tāra", "Tārā", "Vāli"}

# All 31 instances of unaccented Brahma were reviewed in their prose.
# Accentuate the creator only in unambiguous contextual patterns.
CREATOR_BEFORE = re.compile(
    r"(?:received from|dart of|speech of|curse of|of Prajāpati or|"
    r"Vasava answering|place of|permitted by|lord of the gods—)\s*$"
)
CREATOR_AFTER = re.compile(r"^\s*(?:had cursed|had conferred|conferred on|—dwelleth)")


def creator_context(text, match):
    return CREATOR_BEFORE.search(text[max(0, match.start() - 50):match.start()]) or (
        CREATOR_AFTER.match(text[match.end():match.end() + 40])
    )


def normalize_dutt(text, changes=None):
    """Return display text with only reviewed case-sensitive token substitutions."""
    def replace(match):
        original = match[0]
        if original == "Brahma":
            normalized = "Brahmā" if creator_context(text, match) else original
        else:
            normalized = SPELLINGS[original]
        if changes is not None and original != normalized:
            changes[original] += 1
        return normalized

    return TOKEN.sub(replace, text)


def build_audit(sections):
    """Count display substitutions and explicitly deferred tokens across a corpus."""
    substitutions = Counter()
    deferred = Counter()
    section_count = 0
    changed_sections = 0
    legacy = Counter()
    tokens = re.compile(WORD + "+")
    for text in sections:
        section_count += 1
        normalized = normalize_dutt(text, substitutions)
        changed_sections += normalized != text
        display_tokens = tokens.findall(normalized)
        deferred.update(word for word in display_tokens if word in REVIEW_ONLY)
        legacy.update(word for word in display_tokens if "ç" in word.lower())
    return {
        "section_count": section_count,
        "sections_with_replacements": changed_sections,
        "replacement_count": sum(substitutions.values()),
        "replacements": [
            {"original": original, "iast": SPELLINGS.get(original, "Brahmā"), "count": count}
            for original, count in sorted(substitutions.items())
        ],
        "tokens_left_as_printed_for_review": dict(sorted(deferred.items())),
        "residual_cedilla_tokens": dict(sorted(legacy.items())),
        "reference": GLOSSARY_REFERENCE,
    }
